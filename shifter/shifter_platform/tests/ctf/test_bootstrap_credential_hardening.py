"""Fail-closed CTF participant bootstrap credential resolution (issue #1665).

The participant-account service must never fall back to a shared, repo-visible
default password. When neither a per-event ``participant_password_override`` nor
an explicitly configured ``CTF_DEFAULT_PARTICIPANT_PASSWORD`` is present (or a
configured source is too weak), every creation, attach, reset, reveal, and
bootstrap-reuse path must refuse with a controlled error instead of
provisioning a guessable account.
"""

from __future__ import annotations

import pytest
from django.core.cache import caches
from django.urls import reverse

from ctf.exceptions import CTFValidationError
from ctf.models import CTFParticipant
from ctf.services.participant.accounts import (
    create_participant_accounts,
    effective_bootstrap_password,
    reset_participant_credentials,
)
from ctf.services.participant.bulk_import import bulk_import_participants
from management.services import get_user_profile

from .conftest import TEST_CTF_BOOTSTRAP_PASSWORD

pytestmark = pytest.mark.django_db

_UNAVAILABLE = "CTF_BOOTSTRAP_CREDENTIAL_UNAVAILABLE"
_INVALID = "CTF_BOOTSTRAP_CREDENTIAL_INVALID"
_EVENT_OVERRIDE = "EventOnly-Password-42"


@pytest.fixture(autouse=True)
def _clear_login_rate_limit_cache():
    caches["launch_rate_limit"].clear()


@pytest.fixture
def _provisioning_calls(monkeypatch):
    """Record provisioning enqueues so tests can assert none happen on failure."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        "ctf.services.participant.accounts.request_event_provisioning",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    return calls


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def test_resolver_fails_closed_when_no_source_configured(ctf_event, settings):
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""

    with pytest.raises(CTFValidationError) as exc:
        effective_bootstrap_password(ctf_event)

    assert exc.value.code == _UNAVAILABLE


def test_resolver_prefers_validated_event_override_over_platform(ctf_event, settings):
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""
    ctf_event.participant_password_override = _EVENT_OVERRIDE
    ctf_event.save(update_fields=["participant_password_override", "updated_at"])

    assert effective_bootstrap_password(ctf_event) == _EVENT_OVERRIDE


def test_resolver_uses_configured_platform_source(ctf_event, settings):
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = TEST_CTF_BOOTSTRAP_PASSWORD

    assert effective_bootstrap_password(ctf_event) == TEST_CTF_BOOTSTRAP_PASSWORD


def test_resolver_rejects_weak_platform_source(ctf_event, settings):
    # All-numeric and below the minimum-length policy: fails validate_password.
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = "1234"

    with pytest.raises(CTFValidationError) as exc:
        effective_bootstrap_password(ctf_event)

    assert exc.value.code == _INVALID


def test_resolver_rejects_whitespace_only_platform_source(ctf_event, settings):
    # Long enough to pass length/common/numeric validators, yet blank in intent:
    # must be treated as unconfigured, not as an authenticating credential.
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = " " * 12

    with pytest.raises(CTFValidationError) as exc:
        effective_bootstrap_password(ctf_event)

    assert exc.value.code == _UNAVAILABLE


def test_resolver_rejects_whitespace_only_event_override(ctf_event, settings):
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""
    ctf_event.participant_password_override = " " * 12
    ctf_event.save(update_fields=["participant_password_override", "updated_at"])

    with pytest.raises(CTFValidationError) as exc:
        effective_bootstrap_password(ctf_event)

    assert exc.value.code == _UNAVAILABLE


# ---------------------------------------------------------------------------
# Creation / attach atomicity
# ---------------------------------------------------------------------------


def test_create_fails_closed_without_partial_accounts_or_provisioning(ctf_event, settings, _provisioning_calls):
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""

    with pytest.raises(CTFValidationError) as exc:
        create_participant_accounts(ctf_event.id, count=3)

    assert exc.value.code == _UNAVAILABLE
    assert CTFParticipant.objects.filter(event=ctf_event).count() == 0
    assert _provisioning_calls == []


def test_bulk_import_fails_atomically_without_credential(ctf_event, settings, _provisioning_calls):
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""
    csv_content = "Alpha,alpha@example.test\nBravo,bravo@example.test\n"

    with pytest.raises(CTFValidationError) as exc:
        bulk_import_participants(ctf_event.id, csv_content)

    assert exc.value.code == _UNAVAILABLE
    assert CTFParticipant.objects.filter(event=ctf_event).count() == 0
    assert _provisioning_calls == []


# ---------------------------------------------------------------------------
# Reset resolves before mutating
# ---------------------------------------------------------------------------


def test_reset_resolves_before_mutation(ctf_event, settings, _provisioning_calls):
    participant = create_participant_accounts(ctf_event.id, count=1)[0]
    participant.user.set_password("PrivateChangedPassword-42")
    participant.user.save(update_fields=["password"])
    profile = get_user_profile(participant.user)
    profile.must_change_password = False
    profile.save(update_fields=["must_change_password"])

    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""

    with pytest.raises(CTFValidationError) as exc:
        reset_participant_credentials(participant.id)

    assert exc.value.code == _UNAVAILABLE
    participant.user.refresh_from_db()
    profile.refresh_from_db()
    # No mutation: password unchanged and the force-change flag untouched.
    assert participant.user.check_password("PrivateChangedPassword-42")
    assert profile.must_change_password is False


# ---------------------------------------------------------------------------
# Adapters degrade to controlled states, never 500
# ---------------------------------------------------------------------------


def test_detail_view_shows_controlled_unavailable_state(
    authenticated_organizer_client, ctf_event, settings, _provisioning_calls
):
    participant = create_participant_accounts(ctf_event.id, count=1)[0]
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""

    response = authenticated_organizer_client.get(
        reverse("ctf:admin_participant_detail", kwargs={"participant_id": participant.id})
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert "No secure bootstrap password is configured" in body
    assert TEST_CTF_BOOTSTRAP_PASSWORD not in body


def test_resend_invite_returns_400_when_credential_unavailable(
    authenticated_organizer_client, ctf_event, settings, _provisioning_calls
):
    participant = create_participant_accounts(ctf_event.id, count=1)[0]
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""

    response = authenticated_organizer_client.post(
        reverse("v1:ctf:api_participant_resend_invite", kwargs={"participant_id": participant.id})
    )

    assert response.status_code == 400


def test_change_password_survives_unavailable_credential(client, ctf_event_active, settings, _provisioning_calls):
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    client.post(
        reverse("ctf:ctf_login"),
        {"username": participant.user.username, "password": TEST_CTF_BOOTSTRAP_PASSWORD},
    )

    # Operator removes the platform credential after the account was provisioned;
    # the bootstrap-reuse guard must skip rather than 500 the change-password page.
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""
    response = client.post(
        reverse("ctf:ctf_change_password"),
        {
            "old_password": TEST_CTF_BOOTSTRAP_PASSWORD,
            "new_password1": "Fresh-Participant-Pw-99",
            "new_password2": "Fresh-Participant-Pw-99",
        },
    )

    assert response.status_code == 302
    assert get_user_profile(participant.user).must_change_password is False


def test_change_password_rejects_bootstrap_reuse_when_source_unavailable(
    client, ctf_event_active, settings, _provisioning_calls
):
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    client.post(
        reverse("ctf:ctf_login"),
        {"username": participant.user.username, "password": TEST_CTF_BOOTSTRAP_PASSWORD},
    )

    # Operator removed the platform credential, but the account still holds it as
    # its password hash. Reusing that known value as the new password must not
    # clear the forced-change quarantine (issue #1665 quarantine escape).
    settings.CTF_DEFAULT_PARTICIPANT_PASSWORD = ""
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
