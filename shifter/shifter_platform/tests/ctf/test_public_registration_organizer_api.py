"""Organizer review and disposition of public CTF registration requests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.enums import PublicRegistrationDisposition
from ctf.models import CTFParticipant, CTFPublicRegistrationRequest
from shared.audit import bind_audit_writer, get_audit_writer, reset_audit_writer

pytestmark = pytest.mark.django_db


class _FailingAuditWriter:
    """Exercise strict-audit rollback through the shared persistence port."""

    def write(self, event: object) -> None:
        raise RuntimeError("audit unavailable")


def _request(event, *, name="Ada Lovelace", email="ada@example.com"):
    return CTFPublicRegistrationRequest.objects.create(event=event, name=name, email=email)


def _list_url(event) -> str:
    return f"/api/v1/ctf/events/{event.pk}/registration-requests/"


def _disposition_url(request_row) -> str:
    return f"/api/v1/ctf/registration-requests/{request_row.pk}/disposition/"


def test_event_api_round_trips_explicit_publication_and_validated_share_url(
    authenticated_organizer_client,
    ctf_event,
    settings,
):
    settings.SITE_URL = "https://ctf.example.test"

    update = authenticated_organizer_client.put(
        f"/api/v1/ctf/events/{ctf_event.pk}/",
        {"public_registration_enabled": True},
        content_type="application/json",
    )
    detail = authenticated_organizer_client.get(f"/api/v1/ctf/events/{ctf_event.pk}/")

    assert update.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["public_registration_enabled"] is True
    assert detail.json()["public_registration_url"] == (f"https://ctf.example.test/ctf/public/events/{ctf_event.pk}/")


def test_organizer_lists_only_the_event_pending_queue(authenticated_organizer_client, ctf_event, ctf_event_active):
    pending = _request(ctf_event)
    approved = _request(ctf_event, name="Grace", email="grace@example.com")
    approved.disposition = PublicRegistrationDisposition.APPROVED.value
    approved.dispositioned_at = timezone.now()
    approved.save(update_fields=["disposition", "dispositioned_at", "updated_at"])
    _request(ctf_event_active, name="Other", email="other@example.com")

    response = authenticated_organizer_client.get(_list_url(ctf_event))

    assert response.status_code == 200
    assert response.json() == {
        "requests": [
            {
                "id": str(pending.pk),
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "disposition": "pending",
                "created_at": pending.created_at.isoformat().replace("+00:00", "Z"),
            }
        ],
        "total": 1,
    }


def test_pending_queue_is_bounded_by_default(authenticated_organizer_client, ctf_event):
    CTFPublicRegistrationRequest.objects.bulk_create(
        [
            CTFPublicRegistrationRequest(
                event=ctf_event,
                name=f"Registrant {index}",
                email=f"registrant-{index}@example.com",
            )
            for index in range(101)
        ]
    )

    response = authenticated_organizer_client.get(_list_url(ctf_event))

    assert response.status_code == 200
    assert response.json()["total"] == 101
    assert len(response.json()["requests"]) == 100


def test_non_organizer_cannot_read_or_disposition_requests(client, participant_user, ctf_event):
    request_row = _request(ctf_event)
    client.force_login(participant_user)

    assert client.get(_list_url(ctf_event)).status_code == 403
    assert client.post(_disposition_url(request_row), {"action": "reject"}).status_code == 403


def test_approval_uses_canonical_participant_admission_then_closes_request(
    authenticated_organizer_client,
    ctf_event,
):
    request_row = _request(ctf_event)

    response = authenticated_organizer_client.post(
        _disposition_url(request_row),
        {"action": "approve"},
    )

    assert response.status_code == 200
    participant = CTFParticipant.objects.get(event=ctf_event, email="ada@example.com")
    request_row.refresh_from_db()
    assert request_row.disposition == PublicRegistrationDisposition.APPROVED.value
    assert request_row.dispositioned_at is not None
    assert response.json() == {
        "request_id": str(request_row.pk),
        "disposition": "approved",
        "participant_id": str(participant.pk),
    }


def test_rejection_has_no_participant_or_provisioning_side_effect(authenticated_organizer_client, ctf_event):
    request_row = _request(ctf_event)

    response = authenticated_organizer_client.post(
        _disposition_url(request_row),
        {"action": "reject"},
    )

    assert response.status_code == 200
    request_row.refresh_from_db()
    assert request_row.disposition == PublicRegistrationDisposition.REJECTED.value
    assert response.json()["participant_id"] is None
    assert CTFParticipant.objects.filter(event=ctf_event).count() == 0


def test_request_can_be_dispositioned_only_once(authenticated_organizer_client, ctf_event):
    request_row = _request(ctf_event)
    first = authenticated_organizer_client.post(_disposition_url(request_row), {"action": "reject"})
    second = authenticated_organizer_client.post(_disposition_url(request_row), {"action": "reject"})

    assert first.status_code == 200
    assert second.status_code == 409


def test_strict_disposition_audit_failure_rolls_back(ctf_event, organizer_user):
    from ctf.services.public_registration import reject_public_registration_request

    request_row = _request(ctf_event)
    original = get_audit_writer()
    reset_audit_writer()
    bind_audit_writer(_FailingAuditWriter())
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            reject_public_registration_request(request_row.pk, actor_id=organizer_user.pk)
    finally:
        reset_audit_writer()
        bind_audit_writer(original)

    request_row.refresh_from_db()
    assert request_row.disposition == PublicRegistrationDisposition.PENDING.value


def test_strict_publication_audit_failure_rolls_back_enabled_event_creation(organizer_user):
    from ctf.models import CTFEvent
    from ctf.services.event import create_event

    now = timezone.now()
    original = get_audit_writer()
    reset_audit_writer()
    bind_audit_writer(_FailingAuditWriter())
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            create_event(
                organizer_user,
                {
                    "name": "Public event",
                    "event_start": now,
                    "event_end": now + timedelta(hours=2),
                    "public_registration_enabled": True,
                },
            )
    finally:
        reset_audit_writer()
        bind_audit_writer(original)

    assert not CTFEvent.objects.filter(name="Public event").exists()
