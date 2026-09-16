"""Public CTF event publication and registration intake (#2157)."""

from __future__ import annotations

import logging
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from uuid import UUID

import pytest
from django.core.cache import caches
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from ctf.enums import EventStatus
from ctf.models import CTFEvent, CTFParticipant, CTFPublicRegistrationRequest

pytestmark = pytest.mark.django_db


def _publish(event: CTFEvent) -> CTFEvent:
    event.public_registration_enabled = True
    event.save(update_fields=["public_registration_enabled", "updated_at"])
    return event


def test_event_public_registration_is_off_by_default(ctf_event):
    assert ctf_event.public_registration_enabled is False


def test_enabled_public_registration_requires_workspace(ctf_event):
    ctf_event.workspace_id = None
    ctf_event.public_registration_enabled = True

    with pytest.raises(ValidationError) as exc_info:
        ctf_event.full_clean()

    assert "public_registration_enabled" in exc_info.value.message_dict


def test_database_rejects_enabled_unbound_event(ctf_event):
    with pytest.raises(IntegrityError), transaction.atomic():
        CTFEvent.objects.filter(pk=ctf_event.pk).update(
            workspace_id=None,
            public_registration_enabled=True,
        )


def test_database_rejects_terminal_disposition_without_timestamp(ctf_event):
    request_row = CTFPublicRegistrationRequest.objects.create(
        event=ctf_event,
        name="Ada",
        email="ada@example.com",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        CTFPublicRegistrationRequest.objects.filter(pk=request_row.pk).update(
            disposition="rejected",
            dispositioned_at=None,
        )


def test_public_projection_is_allowlisted_and_deadline_aware(ctf_event):
    from ctf.services.public_registration import resolve_public_event

    now = timezone.now()
    ctf_event.description = "Welcome <script>bad()</script>"
    ctf_event.logo_url = "https://attacker.example/logo.png"
    ctf_event.registration_deadline = now
    _publish(ctf_event)
    ctf_event.save(update_fields=["description", "logo_url", "registration_deadline", "updated_at"])

    projection = resolve_public_event(ctf_event.pk, at=now)

    assert projection.event_id == ctf_event.pk
    assert projection.name == ctf_event.name
    assert projection.description == ctf_event.description
    assert projection.registration_open is False
    assert not hasattr(projection, "logo_url")
    assert not hasattr(projection, "workspace_id")
    assert not hasattr(projection, "participant_count")


@pytest.mark.parametrize(
    "mutation",
    [
        {"public_registration_enabled": False},
        {"status": EventStatus.DRAFT.value},
        {"deleted_at": timezone.now()},
    ],
)
def test_public_projection_hides_every_ineligible_variant(ctf_event, mutation):
    from ctf.services.public_registration import PublicEventUnavailable, resolve_public_event

    _publish(ctf_event)
    CTFEvent.all_objects.filter(pk=ctf_event.pk).update(**mutation)

    with pytest.raises(PublicEventUnavailable):
        resolve_public_event(ctf_event.pk)


def test_public_projection_fails_closed_for_a_legacy_unbound_instance(ctf_event):
    from ctf.services.public_registration import PublicEventUnavailable, _project_eligible_event

    ctf_event.public_registration_enabled = True
    ctf_event.workspace_id = None

    with pytest.raises(PublicEventUnavailable):
        _project_eligible_event(ctf_event, at=timezone.now())


def test_public_submission_is_normalized_idempotent_and_has_no_admission_side_effects(ctf_event):
    from ctf.models import CTFPublicRegistrationRequest
    from ctf.services.public_registration import submit_public_registration_request

    _publish(ctf_event)
    before_participants = CTFParticipant.objects.count()

    first = submit_public_registration_request(
        ctf_event.pk,
        name="  Ada Lovelace  ",
        email="  ADA@Example.COM ",
    )
    second = submit_public_registration_request(
        ctf_event.pk,
        name="Different disclosure-resistant name",
        email="ada@example.com",
    )

    assert first.created is True
    assert second.created is False
    assert first.request_id == second.request_id
    request_row = CTFPublicRegistrationRequest.objects.get(pk=first.request_id)
    assert request_row.name == "Ada Lovelace"
    assert request_row.email == "ada@example.com"
    assert CTFPublicRegistrationRequest.objects.filter(event=ctf_event).count() == 1
    assert CTFParticipant.objects.count() == before_participants


def test_public_submission_rechecks_deadline_under_event_lock(ctf_event):
    from ctf.services.public_registration import PublicRegistrationClosed, submit_public_registration_request

    ctf_event.registration_deadline = timezone.now() - timedelta(seconds=1)
    _publish(ctf_event)
    ctf_event.save(update_fields=["registration_deadline", "updated_at"])

    with pytest.raises(PublicRegistrationClosed):
        submit_public_registration_request(ctf_event.pk, name="Ada", email="ada@example.com")


def test_public_submission_enforces_a_bounded_pending_queue(ctf_event, monkeypatch):
    from ctf.services import public_registration

    _publish(ctf_event)
    monkeypatch.setattr(public_registration, "MAX_PENDING_REGISTRATION_REQUESTS", 1)
    public_registration.submit_public_registration_request(ctf_event.pk, name="Ada", email="ada@example.com")

    with pytest.raises(public_registration.PublicRegistrationQueueFull):
        public_registration.submit_public_registration_request(ctf_event.pk, name="Grace", email="grace@example.com")


def test_public_registration_page_escapes_content_and_is_hardened(ctf_event):
    ctf_event.description = '<script src="https://attacker.example/x.js">bad()</script>'
    _publish(ctf_event)
    ctf_event.save(update_fields=["description", "updated_at"])

    response = Client().get(reverse("ctf:public_event_registration", args=[ctf_event.pk]))

    assert response.status_code == 200
    body = response.content.decode()
    assert "&lt;script" in body
    assert "<script" not in body
    assert 'src="https://attacker.example' not in body
    assert "images/favicon.svg" in body
    assert reverse("privacy_notice") in body
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


def test_public_registration_post_requires_csrf_and_returns_generic_success(ctf_event):
    from ctf.models import CTFPublicRegistrationRequest

    _publish(ctf_event)
    url = reverse("ctf:public_event_registration", args=[ctf_event.pk])
    client = Client(enforce_csrf_checks=True)

    assert client.post(url, {"name": "Ada", "email": "ada@example.com"}).status_code == 403
    get_response = client.get(url)
    token = get_response.cookies["csrftoken"].value
    response = client.post(
        url,
        {"name": "Ada", "email": "ada@example.com", "csrfmiddlewaretoken": token},
    )

    assert response.status_code == 200
    body = response.content.decode().lower()
    assert "request has been received" in body
    assert "<output" in body
    assert 'role="status"' not in body
    assert "ada@example.com" not in body
    assert CTFPublicRegistrationRequest.objects.filter(event=ctf_event).count() == 1


def test_public_registration_charges_invalid_attempts_and_fails_closed_on_limiter_error(ctf_event, monkeypatch):
    _publish(ctf_event)
    url = reverse("ctf:public_event_registration", args=[ctf_event.pk])
    cache = caches["launch_rate_limit"]
    cache.clear()

    monkeypatch.setattr("ctf.public_views.PUBLIC_SOURCE_LIMIT", 1)
    first = Client().post(url, {"name": "", "email": "not-an-email"})
    second = Client().post(url, {"name": "", "email": "not-an-email"})
    assert first.status_code == 400
    assert second.status_code == 429

    cache.clear()
    with patch.object(cache, "incr", side_effect=RuntimeError("redis unavailable")):
        unavailable = Client().post(url, {"name": "Ada", "email": "ada@example.com"})
    assert unavailable.status_code == 503
    assert "redis unavailable" not in unavailable.content.decode()


def test_public_registration_sanitizes_event_identifier_in_failure_logs(ctf_event, monkeypatch):
    from ctf import public_views

    monkeypatch.setattr(public_views, "_consume_public_budget", lambda *_args: (_ for _ in ()).throw(RuntimeError()))

    class UnsafeEventID(UUID):
        def __str__(self) -> str:
            return f"{super().__str__()}\nforged-entry"

    event_id = UnsafeEventID(str(ctf_event.pk))
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    public_views.logger.addHandler(handler)
    try:
        response = public_views._admission_rejection(RequestFactory().post("/"), event_id)
    finally:
        public_views.logger.removeHandler(handler)

    assert response is not None
    assert response.status_code == 503
    assert f"{ctf_event.pk}\\nforged-entry" in stream.getvalue()
    assert f"{ctf_event.pk}\nforged-entry" not in stream.getvalue()


def test_public_registration_uses_exact_route_and_safe_methods(ctf_event):
    _publish(ctf_event)
    url = reverse("ctf:public_event_registration", args=[ctf_event.pk])

    assert url == f"/ctf/public/events/{ctf_event.pk}/"
    assert Client().put(url, data=b"{}", content_type="application/json").status_code == 405
    assert Client().get(f"/ctf/public/events/{ctf_event.pk}/anything/").status_code != 200


def test_registration_request_retention_is_event_scoped_and_bounded(
    ctf_event,
    ctf_event_active,
    settings,
):
    from ctf.services.public_registration import purge_expired_public_registration_requests

    now = timezone.now()
    settings.CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS = 24
    ctf_event.event_start = now - timedelta(days=3)
    ctf_event.event_end = now - timedelta(days=2)
    ctf_event.save(update_fields=["event_start", "event_end", "updated_at"])
    expired = CTFPublicRegistrationRequest.objects.create(
        event=ctf_event,
        name="Expired",
        email="expired@example.com",
    )
    still_retained = CTFPublicRegistrationRequest.objects.create(
        event=ctf_event_active,
        name="Retained",
        email="retained@example.com",
    )

    assert purge_expired_public_registration_requests(at=now, batch_size=1) == 1
    assert not CTFPublicRegistrationRequest.all_objects.filter(pk=expired.pk).exists()
    assert CTFPublicRegistrationRequest.objects.filter(pk=still_retained.pk).exists()
