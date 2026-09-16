"""CTF participant bootstrap credential hardening regressions.

New isolated accounts receive a unique generated credential unless an event
explicitly opts into a validated shared credential. Platform-wide defaults,
password retrieval, and invitation-triggered credential resets are forbidden.
"""

from __future__ import annotations

import pytest
from django.core.cache import caches
from django.urls import reverse

from ctf.exceptions import CTFValidationError
from ctf.models import CTFParticipant
from ctf.services.participant.accounts import create_participant_accounts
from ctf.services.participant.bulk_import import bulk_import_participants
from management.services import get_user_profile

from .conftest import TEST_CTF_BOOTSTRAP_PASSWORD

pytestmark = pytest.mark.django_db

_INVALID = "CTF_PARTICIPANT_PASSWORD_INVALID"
_EVENT_OVERRIDE = "EventOnly-Password-42"


@pytest.fixture(autouse=True)
def _clear_login_rate_limit_cache():
    caches["launch_rate_limit"].clear()


@pytest.fixture
def _provisioning_calls(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        "ctf.services.participant.accounts.request_event_provisioning",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    return calls


def test_creation_generates_unique_credentials_without_event_policy(
    ctf_event,
    settings,
    _provisioning_calls,
    monkeypatch,
):
    ctf_event.participant_password_override = ""
    ctf_event.save(update_fields=["participant_password_override", "updated_at"])
    # A legacy dynamic setting must have no effect.
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = "1234"
    generated_passwords = iter(["Generated-Alpha-Password-42", "Generated-Bravo-Password-84"])
    monkeypatch.setattr(
        "ctf.services.participant.accounts.generate_participant_password",
        lambda *, user=None: next(generated_passwords),
    )

    participants = create_participant_accounts(ctf_event.id, count=2)

    assert len(participants) == 2
    assert not participants[0].user.check_password("1234")
    assert participants[0].user.check_password("Generated-Alpha-Password-42")
    assert not participants[0].user.check_password("Generated-Bravo-Password-84")
    assert participants[1].user.check_password("Generated-Bravo-Password-84")
    assert not participants[1].user.check_password("Generated-Alpha-Password-42")


def test_creation_uses_validated_event_shared_credential(ctf_event, _provisioning_calls):
    ctf_event.participant_password_override = _EVENT_OVERRIDE
    ctf_event.save(update_fields=["participant_password_override", "updated_at"])

    participant = create_participant_accounts(ctf_event.id, count=1)[0]

    assert participant.user.check_password(_EVENT_OVERRIDE)


def test_invalid_event_shared_credential_fails_atomically(ctf_event, _provisioning_calls):
    ctf_event.participant_password_override = "1234"
    ctf_event.save(update_fields=["participant_password_override", "updated_at"])

    with pytest.raises(CTFValidationError) as exc:
        create_participant_accounts(ctf_event.id, count=3)

    assert exc.value.code == _INVALID
    assert CTFParticipant.objects.filter(event=ctf_event).count() == 0
    assert _provisioning_calls == []


def test_bulk_import_generates_accounts_without_shared_credential(
    ctf_event,
    _provisioning_calls,
    monkeypatch,
):
    ctf_event.participant_password_override = ""
    ctf_event.save(update_fields=["participant_password_override", "updated_at"])
    generated_passwords = iter(["Generated-Import-Alpha-42", "Generated-Import-Bravo-84"])
    monkeypatch.setattr(
        "ctf.services.participant.accounts.generate_participant_password",
        lambda *, user=None: next(generated_passwords),
    )

    result = bulk_import_participants(
        ctf_event.id,
        "Alpha,alpha@example.test\nBravo,bravo@example.test\n",
    )

    created = result["created"]
    assert len(created) == 2
    assert CTFParticipant.objects.filter(event=ctf_event).count() == 2
    assert created[0].user.check_password("Generated-Import-Alpha-42")
    assert not created[0].user.check_password("Generated-Import-Bravo-84")
    assert created[1].user.check_password("Generated-Import-Bravo-84")
    assert not created[1].user.check_password("Generated-Import-Alpha-42")


def test_detail_view_never_retrieves_existing_credential(
    authenticated_organizer_client,
    ctf_event,
    _provisioning_calls,
):
    participant = create_participant_accounts(ctf_event.id, count=1)[0]

    response = authenticated_organizer_client.get(
        reverse("ctf:admin_participant_detail", kwargs={"participant_id": participant.id})
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert TEST_CTF_BOOTSTRAP_PASSWORD not in body
    assert "Reveal" not in body
    assert 'id="root"' in body


def test_resend_invite_does_not_mutate_password(
    authenticated_organizer_client,
    ctf_event,
    _provisioning_calls,
    monkeypatch,
):
    sent: list[dict] = []
    monkeypatch.setattr("ctf.services.notification._send_email", lambda **kwargs: sent.append(kwargs))
    participant = create_participant_accounts(
        ctf_event.id,
        count=1,
        email="delivery@example.test",
    )[0]
    participant.user.set_password("PrivateChangedPassword-42")
    participant.user.save(update_fields=["password"])

    response = authenticated_organizer_client.post(
        reverse("v1:ctf:api_participant_resend_invite", kwargs={"participant_id": participant.id})
    )

    participant.user.refresh_from_db()
    assert response.status_code == 200
    assert participant.user.check_password("PrivateChangedPassword-42")
    assert len(sent) == 1
    assert "PrivateChangedPassword-42" not in sent[0]["text_content"]
    assert TEST_CTF_BOOTSTRAP_PASSWORD not in sent[0]["text_content"]


def test_first_password_change_rejects_current_issued_password(
    client,
    ctf_event_active,
    _provisioning_calls,
):
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    client.post(
        reverse("ctf:ctf_login"),
        {"username": participant.user.username, "password": TEST_CTF_BOOTSTRAP_PASSWORD},
    )

    response = client.post(
        reverse("ctf:ctf_change_password"),
        {
            "old_password": TEST_CTF_BOOTSTRAP_PASSWORD,
            "new_password1": TEST_CTF_BOOTSTRAP_PASSWORD,
            "new_password2": TEST_CTF_BOOTSTRAP_PASSWORD,
        },
    )

    assert response.status_code == 200
    assert "Choose a password different from the event bootstrap password" in response.content.decode()
    assert get_user_profile(participant.user).must_change_password is True
