"""Isolated temporary CTF participant account behavior (issue #1206)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFValidationError
from ctf.services.participant.accounts import (
    create_participant_accounts,
    purge_expired_participant_accounts,
    rename_participant_username,
)
from ctf.services.participant.bulk_import import bulk_import_participants
from ctf.services.participant.credentials import reset_participant_credentials
from ctf.services.participant.lifecycle import add_participant
from ctf.services.participant.moderation import disqualify_participant
from management.services import get_user_profile

from .conftest import TEST_CTF_BOOTSTRAP_PASSWORD

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_login_rate_limit_cache():
    caches["launch_rate_limit"].clear()


def test_account_creation_never_reuses_platform_user_by_email(ctf_event, standard_user, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)

    participants = create_participant_accounts(
        ctf_event.id,
        count=1,
        email=standard_user.email,
        display_name="CTF Seat",
    )

    participant = participants[0]
    assert participant.user_id != standard_user.id
    assert participant.user.email == ""
    assert participant.email == standard_user.email
    assert participant.user.check_password(TEST_CTF_BOOTSTRAP_PASSWORD)


def test_account_creation_marks_low_privilege_force_change_account(ctf_event, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)

    participant = create_participant_accounts(ctf_event.id, count=1)[0]
    profile = get_user_profile(participant.user)

    assert participant.email == ""
    assert participant.user.username.startswith("range-")
    assert profile.is_ctf_account is True
    assert profile.must_change_password is True
    assert profile.user_type == "ctf_participant"
    assert participant.user.is_staff is False
    assert participant.user.is_superuser is False
    assert set(participant.user.groups.values_list("name", flat=True)) == {"CTF Participant"}


def test_ctf_login_rejects_platform_accounts(client, standard_user):
    response = client.post(
        reverse("ctf:ctf_login"),
        {"username": standard_user.username, "password": "testpass123"},
    )

    assert response.status_code == 200
    assert "Invalid username or password" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_ctf_login_forces_password_change(client, ctf_event_active, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]

    response = client.post(
        reverse("ctf:ctf_login"),
        {"username": participant.user.username, "password": TEST_CTF_BOOTSTRAP_PASSWORD},
    )

    assert response.status_code == 302
    assert response.url == reverse("ctf:ctf_change_password")
    assert str(participant.user_id) == client.session["_auth_user_id"]


def test_organizer_can_rename_participant_username(ctf_event, organizer_user, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event.id, count=1)[0]

    rename_participant_username(participant.id, "range-blue-team", actor=organizer_user)

    participant.user.refresh_from_db()
    assert participant.user.username == "range-blue-team"
    assert not User.objects.filter(username__iexact="range-blue-team").exclude(pk=participant.user_id).exists()


def test_ctf_account_boundary_denies_non_participant_surface(ctf_event_active, monkeypatch):
    from config.middleware import CTFAccountBoundaryMiddleware

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    request = RequestFactory().get("/mission-control/")
    request.user = participant.user

    response = CTFAccountBoundaryMiddleware(lambda _request: HttpResponse("escaped"))(request)

    assert response.status_code == 403
    assert response.content == b"Forbidden"


def test_force_change_boundary_redirects_before_ctf_surface(ctf_event_active, monkeypatch):
    from config.middleware import CTFAccountBoundaryMiddleware

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    request = RequestFactory().get("/ctf/range/")
    request.user = participant.user

    response = CTFAccountBoundaryMiddleware(lambda _request: HttpResponse("escaped"))(request)

    assert response.status_code == 302
    assert response.url == reverse("ctf:ctf_change_password")


def _boundary_response(user, path):
    """Run the CTF account boundary middleware for ``user`` against ``path``."""
    from config.middleware import CTFAccountBoundaryMiddleware

    request = RequestFactory().get(path)
    request.user = user
    return CTFAccountBoundaryMiddleware(lambda _request: HttpResponse("escaped"))(request)


def test_ctf_boundary_admits_live_participant_spa_bootstrap_and_range_access(ctf_event_active, monkeypatch):
    # Issue #1740: a live participant must reach the Mission Control Guacamole
    # range-access surfaces (terminal page + RDP/SSH bootstrap + status/open)
    # for their own box.
    from management.services import set_ctf_password_change_required

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    # Simulate the post-first-login state so the boundary evaluates the surface
    # rule rather than the forced-password-change redirect.
    set_ctf_password_change_required(participant.user, False)
    user = User.objects.get(pk=participant.user_id)

    for path in (
        "/api/v1/bootstrap/",
        "/api/v1/mission-control/guacamole/rdp-url/",
        "/api/v1/mission-control/guacamole/ssh-url/",
        "/api/v1/mission-control/guacamole/bootstrap/00000000-0000-0000-0000-000000000000/",
        "/api/v1/mission-control/guacamole/bootstrap/00000000-0000-0000-0000-000000000000/open/",
        "/mission-control/terminal/",
    ):
        response = _boundary_response(user, path)
        assert response.status_code == 200, path
        assert response.content == b"escaped", path


def _websocket_boundary_messages(user, path):
    """Run the CTF WebSocket boundary and return downstream calls/messages."""
    from config.websocket_auth import CTFAccountWebSocketBoundary

    downstream_calls = []
    messages = []

    async def downstream(scope, receive, send):
        downstream_calls.append(scope["path"])

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        messages.append(message)

    boundary = CTFAccountWebSocketBoundary(downstream)
    asyncio.run(boundary({"user": user, "path": path}, receive, send))
    return downstream_calls, messages


@pytest.mark.django_db(transaction=True)
def test_ctf_websocket_boundary_admits_live_participant_terminal(ctf_event_active, monkeypatch):
    from management.services import set_ctf_password_change_required

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    set_ctf_password_change_required(participant.user, False)

    calls, messages = _websocket_boundary_messages(
        User.objects.get(pk=participant.user_id),
        "/ws/terminal/00000000-0000-0000-0000-000000000000/",
    )

    assert calls == ["/ws/terminal/00000000-0000-0000-0000-000000000000/"]
    assert messages == []


@pytest.mark.django_db(transaction=True)
def test_ctf_websocket_boundary_denies_other_platform_socket(ctf_event_active, monkeypatch):
    from management.services import set_ctf_password_change_required

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    set_ctf_password_change_required(participant.user, False)

    calls, messages = _websocket_boundary_messages(
        User.objects.get(pk=participant.user_id),
        "/ws/range-status/00000000-0000-0000-0000-000000000000/",
    )

    assert calls == []
    assert messages == [{"type": "websocket.close", "code": 4403}]


@pytest.mark.django_db(transaction=True)
def test_ctf_websocket_boundary_denies_terminal_before_password_change(ctf_event_active, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]

    calls, messages = _websocket_boundary_messages(
        User.objects.get(pk=participant.user_id),
        "/ws/terminal/00000000-0000-0000-0000-000000000000/",
    )

    assert calls == []
    assert messages == [{"type": "websocket.close", "code": 4403}]


def test_live_participant_can_load_real_spa_bootstrap(client, ctf_event_active, monkeypatch):
    from management.services import set_ctf_password_change_required

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    set_ctf_password_change_required(participant.user, False)
    client.force_login(participant.user)

    response = client.get("/api/v1/bootstrap/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["principal"]["username"] == participant.user.username
    assert payload["permissions"]["is_ctf_participant"] is True
    assert payload["modes"] == {"participant": True, "operator": False, "default": "participant"}


def test_ctf_boundary_still_denies_non_guacamole_mission_control(ctf_event_active, monkeypatch):
    # The exception is narrow: NGFW, range lifecycle, credentials, and the
    # rest of Mission Control stay blocked for temporary accounts (issue #1740).
    from management.services import set_ctf_password_change_required

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    set_ctf_password_change_required(participant.user, False)
    user = User.objects.get(pk=participant.user_id)

    for path in (
        "/api/v1/bootstrap/admin/",
        "/api/v1/mission-control/ngfw/00000000-0000-0000-0000-000000000000/ssh-url/",
        "/api/v1/mission-control/range/launch/",
        "/api/v1/mission-control/credentials/",
        "/mission-control/",
        "/mission-control/agents/",
    ):
        response = _boundary_response(user, path)
        assert response.status_code == 403, path
        assert response.content == b"Forbidden", path


def test_ctf_boundary_denies_guacamole_for_non_live_participant(ctf_event, monkeypatch):
    # The live-participant gate still applies to the guacamole prefix: a temporary
    # account with no live participation (event not active) is denied (issue #1740).
    from management.services import set_ctf_password_change_required

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event.id, count=1)[0]
    set_ctf_password_change_required(participant.user, False)
    user = User.objects.get(pk=participant.user_id)

    response = _boundary_response(user, "/api/v1/mission-control/guacamole/rdp-url/")

    assert response.status_code == 403
    assert response.content == b"Forbidden"


def test_platform_password_backend_rejects_ctf_credentials(ctf_event_active, monkeypatch):
    from config.auth import PlatformModelBackend

    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]

    authenticated = PlatformModelBackend().authenticate(
        None,
        username=participant.user.username,
        password=TEST_CTF_BOOTSTRAP_PASSWORD,
    )

    assert authenticated is None


def test_single_invite_accepts_no_email_and_creates_isolated_account(ctf_event, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    ctf_event.participant_password_override = ""
    ctf_event.save(update_fields=["participant_password_override", "updated_at"])
    monkeypatch.setattr(
        "ctf.services.participant.accounts.generate_participant_password",
        lambda *, user=None: "Generated-Invite-Password-42",
    )

    participant = add_participant(ctf_event.id, "", "Walk-in")

    assert participant.email == ""
    assert participant.user is not None
    assert participant.user.profile.is_ctf_account is True
    assert participant.user.check_password("Generated-Invite-Password-42")


class TestImmediateSeatProvisioning:
    """#535 / CTF-006: organizer creation provisions a registered seat with no transient INVITED hop."""

    @staticmethod
    def _stub_provisioning(monkeypatch):
        monkeypatch.setattr(
            "ctf.services.participant.accounts.request_event_provisioning",
            lambda *_a, **_kw: None,
        )

    def test_single_add_lands_registered_with_account(self, ctf_event, monkeypatch):
        """A single organizer add returns a registered participation with a linked isolated account."""
        self._stub_provisioning(monkeypatch)

        participant = add_participant(ctf_event.id, "solo@example.test", "Solo")

        assert participant.status == ParticipantStatus.REGISTERED.value
        assert participant.user is not None
        assert participant.registered_at is not None
        # Provisioned, not invited: login-info delivery does not happen at creation.
        assert participant.login_info_sent_at is None

    def test_bulk_import_lands_registered_with_accounts(self, ctf_event, monkeypatch):
        """Every CSV-imported row is provisioned and registered, never left invited."""
        self._stub_provisioning(monkeypatch)

        result = bulk_import_participants(ctf_event.id, "Ann,ann@example.test\nBob,bob@example.test")

        assert len(result["created"]) == 2
        for participant in result["created"]:
            assert participant.status == ParticipantStatus.REGISTERED.value
            assert participant.user is not None
            assert participant.registered_at is not None

    def test_generated_seats_land_registered_with_accounts(self, ctf_event, monkeypatch):
        """Count-provisioned seats are registered with isolated accounts."""
        self._stub_provisioning(monkeypatch)

        created = create_participant_accounts(ctf_event.id, count=3)

        assert len(created) == 3
        for participant in created:
            assert participant.status == ParticipantStatus.REGISTERED.value
            assert participant.user is not None

    def test_every_organizer_path_lands_registered(self, ctf_event, monkeypatch):
        """Every organizer creation path yields a registered participation and no other status."""
        self._stub_provisioning(monkeypatch)

        add_participant(ctf_event.id, "a@example.test", "A")
        bulk_import_participants(ctf_event.id, "B,b@example.test")
        create_participant_accounts(ctf_event.id, count=1)

        statuses = set(ctf_event.participants.values_list("status", flat=True))
        assert statuses == {ParticipantStatus.REGISTERED.value}


def test_delivery_email_unique_per_event_not_global(ctf_event, ctf_event_active, monkeypatch):
    """CTF-601: one email per event; email still isn't a global identity key."""
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)

    first = add_participant(ctf_event.id, "shared@example.test", "First")
    with pytest.raises(CTFValidationError):
        add_participant(ctf_event.id, "shared@example.test", "Second")
    other_event = add_participant(ctf_event_active.id, "shared@example.test", "Elsewhere")

    assert first.user_id != other_event.user_id


def test_legacy_resend_preserves_password_and_sends_login_information(ctf_event, monkeypatch):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    sent = []
    monkeypatch.setattr("ctf.services.notification._send_email", lambda **kwargs: sent.append(kwargs))
    participant = create_participant_accounts(
        ctf_event.id,
        count=1,
        email="delivery@example.test",
    )[0]
    participant.user.set_password("PrivateChangedPassword-42")
    participant.user.save(update_fields=["password"])
    profile = get_user_profile(participant.user)
    profile.must_change_password = False
    profile.save(update_fields=["must_change_password"])

    reset_participant_credentials(participant.id)

    participant.user.refresh_from_db()
    profile.refresh_from_db()
    assert participant.user.check_password("PrivateChangedPassword-42")
    assert profile.must_change_password is False
    assert len(sent) == 1
    assert participant.user.username in sent[0]["text_content"]
    assert TEST_CTF_BOOTSTRAP_PASSWORD not in sent[0]["text_content"]
    assert "PrivateChangedPassword-42" not in sent[0]["text_content"]


def test_disqualification_keeps_account_live_for_view_access(ctf_event, monkeypatch):
    """CTF-609: disqualification records a reason and keeps login intact (view-only access)."""
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event.id, count=1, email="private@example.test")[0]

    disqualify_participant(participant.id, "rules")

    participant.refresh_from_db()
    participant.user.refresh_from_db()
    profile = get_user_profile(participant.user)
    assert participant.status == "disqualified"
    assert participant.status_reason == "rules"
    assert participant.user.is_active is True
    assert participant.user.has_usable_password() is True
    assert profile.anonymized_at is None


def test_post_event_retention_purge_anonymizes_accounts(ctf_event_active, monkeypatch, settings):
    monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
    participant = create_participant_accounts(ctf_event_active.id, count=1)[0]
    ctf_event_active.event_start = timezone.now() - timedelta(hours=2)
    ctf_event_active.event_end = timezone.now() - timedelta(hours=1)
    ctf_event_active.save(update_fields=["event_start", "event_end", "updated_at"])
    settings.CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS = 0

    count = purge_expired_participant_accounts()

    participant.user.refresh_from_db()
    assert count == 1
    assert participant.user.is_active is False


def test_ctf_login_rate_limits_repeated_failures(client, standard_user, settings):
    settings.CTF_LOGIN_RATE_LIMIT_MAX = 2
    settings.CTF_LOGIN_SOURCE_RATE_LIMIT_MAX = 20
    settings.CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300

    client.post(reverse("ctf:ctf_login"), {"username": standard_user.username, "password": "wrong"})
    client.post(reverse("ctf:ctf_login"), {"username": standard_user.username, "password": "wrong"})
    response = client.post(
        reverse("ctf:ctf_login"),
        {"username": standard_user.username, "password": "wrong"},
    )

    assert response.status_code == 429
    assert response["Retry-After"] == "300"


def test_ctf_login_allows_event_users_behind_shared_source(client, settings):
    settings.CTF_LOGIN_RATE_LIMIT_MAX = 2
    settings.CTF_LOGIN_SOURCE_RATE_LIMIT_MAX = 6
    settings.CTF_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 300

    for participant_number in range(6):
        response = client.post(
            reverse("ctf:ctf_login"),
            {"username": f"event-participant-{participant_number}", "password": "wrong"},
        )
        assert response.status_code == 200

    response = client.post(
        reverse("ctf:ctf_login"),
        {"username": "event-participant-7", "password": "wrong"},
    )

    assert response.status_code == 429
    assert response["Retry-After"] == "300"
