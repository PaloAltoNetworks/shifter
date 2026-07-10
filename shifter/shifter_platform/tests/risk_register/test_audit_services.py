"""Behavior tests for risk_register.services audit logging functions.

Drives the real audit functions against real ``AuditLog`` rows instead of
patching ``AuditLog.log``; each test asserts on the persisted row the service
returned. The one failure-path test triggers a real serialization rejection
(a non-JSON payload) rather than mocking the manager to raise, exercising the
"audit logging never breaks the caller" swallow through a real boundary fault.

The request-context helpers (``get_client_ip`` / ``get_request_id`` /
``get_actor_from_request``) take a request object as input; building that input
with ``MagicMock`` is not a first-party patch, so those tests are unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from risk_register.audit_health import get_audit_health_snapshot, reset_audit_health
from risk_register.models import AuditLog
from risk_register.services import (
    AuditEvent,
    AuthPrincipal,
    RequestAudit,
    SessionInfo,
    StateChange,
    audit_auth_event,
    audit_log,
    audit_log_from_request,
    audit_log_system_event,
    audit_role_sync,
    audit_session_event,
    get_actor_from_request,
    get_client_ip,
    get_request_id,
    select_trusted_client_ip,
)

# ---- Fixtures ----


@pytest.fixture(autouse=True)
def _reset_audit_health_state():
    reset_audit_health()
    yield
    reset_audit_health()


@pytest.fixture
def staff_user():
    """Authenticated principal input (an id-bearing value, no DB row needed)."""
    return Mock(
        pk=42,
        id=42,
        email="test@example.com",
        username="testuser",
        is_authenticated=True,
    )


@pytest.fixture
def mock_request(staff_user):
    """HttpRequest input with an authenticated user."""
    request = MagicMock()
    request.user = staff_user
    request.META = {
        "HTTP_X_FORWARDED_FOR": "10.0.0.1, 10.0.0.2",
        "HTTP_USER_AGENT": "TestBrowser/1.0",
        "HTTP_X_REQUEST_ID": "req-abc-123",
        "REMOTE_ADDR": "127.0.0.1",
    }
    request.request_id = None  # No middleware request_id
    return request


@pytest.fixture
def mock_request_simple():
    """Request input with only REMOTE_ADDR (no XFF, no auth)."""
    request = MagicMock()
    request.user = MagicMock()
    request.user.is_authenticated = False
    request.auth = None
    request.META = {
        "REMOTE_ADDR": "192.168.1.1",
        "HTTP_USER_AGENT": "SimpleAgent/2.0",
    }
    request.request_id = None
    return request


@pytest.fixture
def mock_apikey_request():
    """Request input with API key authentication."""
    request = MagicMock()
    request.user = MagicMock()
    request.user.is_authenticated = False
    request.auth = MagicMock()
    request.auth.id = 42
    request.META = {
        "REMOTE_ADDR": "10.10.10.10",
        "HTTP_USER_AGENT": "APIClient/1.0",
    }
    request.request_id = None
    return request


# ---- audit_log() ----


@pytest.mark.django_db
class TestAuditLog:
    def test_creates_entry_with_correct_fields(self, staff_user):
        entry = audit_log(
            AuditEvent(
                entity_type=AuditLog.EntityType.RANGE,
                entity_id=42,
                action=AuditLog.Action.CREATE,
                actor_type=AuditLog.ActorType.USER,
                actor_id=staff_user.id,
                new_state={"scenario": "test"},
                context="test context",
                source_ip="10.0.0.1",
                user_agent="TestAgent",
                request_id="req-123",
            )
        )

        assert entry is not None
        stored = AuditLog.objects.get(pk=entry.pk)
        assert stored.entity_type == AuditLog.EntityType.RANGE
        assert stored.entity_id == 42
        assert stored.action == AuditLog.Action.CREATE
        assert stored.actor_type == AuditLog.ActorType.USER
        assert stored.actor_id == staff_user.id
        assert stored.new_state == {"scenario": "test"}
        assert stored.context == "test context"
        assert stored.source_ip == "10.0.0.1"
        assert stored.user_agent == "TestAgent"
        assert stored.request_id == "req-123"

    def test_strict_reraises_on_persistence_failure(self):
        """With ``strict=True`` a persistence fault propagates instead of None.

        The role-sync audit path needs fail-closed behavior so a failed audit
        rolls back the role mutation it describes (issue #937 SEC-5).
        """
        with pytest.raises(TypeError):
            audit_log(
                AuditEvent(
                    entity_type=AuditLog.EntityType.USER,
                    entity_id=1,
                    action=AuditLog.Action.ROLE_SYNC,
                    new_state={"bad": {1, 2, 3}},
                ),
                strict=True,
            )

    def test_returns_none_when_row_cannot_be_persisted(self):
        """A real serialization failure is swallowed; the caller gets None.

        ``new_state`` is a JSONField, so a non-serializable value (a set) is
        rejected by the encoder during the write — a real boundary fault, not a
        mocked one. ``audit_log`` must return None rather than propagate, which
        is the whole contract of its except branch ("audit logging never breaks
        the caller"). The failed write poisons the surrounding test transaction,
        so no follow-up query is issued here.
        """
        result = audit_log(
            AuditEvent(
                entity_type=AuditLog.EntityType.RANGE,
                entity_id=1,
                action=AuditLog.Action.CREATE,
                new_state={"bad": {1, 2, 3}},
            )
        )
        assert result is None

    def test_returns_none_failure_marks_audit_health_degraded(self):
        result = audit_log(
            AuditEvent(
                entity_type=AuditLog.EntityType.RANGE,
                entity_id=1,
                action=AuditLog.Action.CREATE,
                new_state={"bad": {1, 2, 3}},
            )
        )

        snapshot = get_audit_health_snapshot()
        assert result is None
        assert snapshot.degraded is True
        assert snapshot.failure_count == 1
        assert snapshot.last_failure_reason == "TypeError"

    def test_strict_failure_marks_audit_health_degraded_before_reraising(self):
        with pytest.raises(TypeError):
            audit_log(
                AuditEvent(
                    entity_type=AuditLog.EntityType.USER,
                    entity_id=1,
                    action=AuditLog.Action.ROLE_SYNC,
                    new_state={"bad": {1, 2, 3}},
                ),
                strict=True,
            )

        snapshot = get_audit_health_snapshot()
        assert snapshot.degraded is True
        assert snapshot.failure_count == 1
        assert snapshot.last_failure_reason == "TypeError"


# ---- audit_role_sync() ----


@pytest.mark.django_db
class TestAuditRoleSync:
    def test_records_role_change_row(self):
        entry = audit_role_sync(
            user_id=7,
            actor_type=AuditLog.ActorType.USER,
            actor_id=7,
            change=StateChange(
                previous={"user_type": "standard", "groups": []},
                new={"user_type": "ctf_participant", "groups": ["CTF Participant"]},
            ),
            source="oidc",
            request=RequestAudit(source_ip="9.9.9.9"),
        )
        stored = AuditLog.objects.get(pk=entry.pk)
        assert stored.action == AuditLog.Action.ROLE_SYNC
        assert stored.entity_type == AuditLog.EntityType.USER
        assert stored.entity_id == 7
        assert stored.actor_type == AuditLog.ActorType.USER
        assert stored.previous_state == {"user_type": "standard", "groups": []}
        assert stored.new_state == {"user_type": "ctf_participant", "groups": ["CTF Participant"]}
        assert stored.source_ip == "9.9.9.9"

    def test_raises_when_row_cannot_be_persisted(self):
        """Fail-closed: a persistence fault propagates so callers can roll back."""
        with pytest.raises(TypeError):
            audit_role_sync(
                user_id=1,
                actor_type=AuditLog.ActorType.USER,
                actor_id=1,
                change=StateChange(previous={"user_type": "standard"}, new={"groups": {1, 2, 3}}),
                source="oidc",
            )


# ---- audit_log_from_request() ----


@pytest.mark.django_db
class TestAuditLogFromRequest:
    def test_extracts_request_context(self, mock_request, staff_user):
        entry = audit_log_from_request(
            mock_request,
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=1,
            action=AuditLog.Action.CREATE,
        )

        assert entry is not None
        stored = AuditLog.objects.get(pk=entry.pk)
        assert stored.actor_type == AuditLog.ActorType.USER
        assert stored.actor_id == staff_user.id
        # Rightmost (ALB-appended) hop, not the spoofable leftmost value.
        assert stored.source_ip == "10.0.0.2"
        assert stored.user_agent == "TestBrowser/1.0"
        assert stored.request_id == "req-abc-123"

    def test_handles_apikey_auth(self, mock_apikey_request):
        entry = audit_log_from_request(
            mock_apikey_request,
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=1,
            action=AuditLog.Action.CREATE,
        )

        assert entry is not None
        assert entry.actor_type == AuditLog.ActorType.APIKEY
        assert entry.actor_id == 42


# ---- audit_log_system_event() ----


@pytest.mark.django_db
class TestAuditLogSystemEvent:
    def test_prefixes_source_to_context(self):
        entry = audit_log_system_event(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=1,
            action=AuditLog.Action.READY,
            source="engine.handlers",
            context="range provisioned",
        )

        assert entry is not None
        assert entry.context == "[engine.handlers] range provisioned"
        assert entry.actor_type == AuditLog.ActorType.SYSTEM

    def test_source_only_context(self):
        entry = audit_log_system_event(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=1,
            action=AuditLog.Action.READY,
            source="engine.handlers",
        )
        assert entry.context == "[engine.handlers]"


# ---- audit_auth_event() ----


@pytest.mark.django_db
class TestAuditAuthEvent:
    def test_records_login_event(self, staff_user):
        entry = audit_auth_event(
            action=AuditLog.Action.LOGIN,
            principal=AuthPrincipal(
                user_id=staff_user.id,
                email="test@example.com",
                cognito_sub="abc-123",
            ),
            source_ip="10.0.0.1",
            user_agent="Browser/1.0",
        )

        assert entry is not None
        stored = AuditLog.objects.get(pk=entry.pk)
        assert stored.action == AuditLog.Action.LOGIN
        assert stored.entity_type == AuditLog.EntityType.USER
        assert stored.new_state == {"email": "test@example.com", "cognito_sub": "abc-123"}
        assert stored.actor_type == AuditLog.ActorType.COGNITO


# ---- audit_session_event() ----


@pytest.mark.django_db
class TestAuditSessionEvent:
    def test_records_connect_event(self, staff_user):
        entry = audit_session_event(
            action=AuditLog.Action.CONNECT,
            user_id=staff_user.id,
            session=SessionInfo(
                session_id="sess-abc",
                range_id=42,
                session_type="terminal",
                target_ip="172.16.0.5",
            ),
            source_ip="10.0.0.1",
        )

        assert entry is not None
        stored = AuditLog.objects.get(pk=entry.pk)
        assert stored.action == AuditLog.Action.CONNECT
        assert stored.entity_type == AuditLog.EntityType.SESSION
        assert stored.new_state["session_id"] == "sess-abc"
        assert stored.new_state["range_id"] == 42
        assert stored.new_state["session_type"] == "terminal"
        assert stored.new_state["target_ip"] == "172.16.0.5"

    def test_records_user_email_when_provided(self, staff_user):
        """Session rows carry the user email so lifecycle events are attributable."""
        entry = audit_session_event(
            action=AuditLog.Action.DISCONNECT,
            user_id=staff_user.id,
            session=SessionInfo(
                session_id="sess-xyz",
                session_type="terminal",
                email="operator@example.com",
            ),
            context="close_code=1000 reason=idle_timeout",
        )

        assert entry is not None
        stored = AuditLog.objects.get(pk=entry.pk)
        assert stored.new_state["email"] == "operator@example.com"

    def test_omits_email_key_when_absent(self, staff_user):
        """No email is stored when the session has none, keeping rows minimal."""
        entry = audit_session_event(
            action=AuditLog.Action.CONNECT,
            user_id=staff_user.id,
            session=SessionInfo(session_id="sess-noemail", session_type="terminal"),
        )

        assert entry is not None
        stored = AuditLog.objects.get(pk=entry.pk)
        assert "email" not in stored.new_state


# ---- get_client_ip() ----


class TestGetClientIp:
    def test_xff_rightmost_trusted_hop(self, mock_request):
        """Behind one trusted proxy, the rightmost (appended) hop is the client.

        The leftmost value ``10.0.0.1`` is attacker-controlled and must be
        ignored in favour of the proxy-appended ``10.0.0.2`` (SEC-4).
        """
        ip = get_client_ip(mock_request)
        assert ip == "10.0.0.2"

    def test_remote_addr_fallback(self, mock_request_simple):
        ip = get_client_ip(mock_request_simple)
        assert ip == "192.168.1.1"


# ---- select_trusted_client_ip() ----


class TestSelectTrustedClientIp:
    def test_returns_rightmost_hop_with_default_single_proxy(self):
        ip = select_trusted_client_ip("1.2.3.4, 9.9.9.9", "10.0.0.1", trusted_hops=1)
        assert ip == "9.9.9.9"

    def test_forged_leftmost_value_is_ignored(self):
        ip = select_trusted_client_ip("127.0.0.1, 9.9.9.9", "10.0.0.1", trusted_hops=1)
        assert ip == "9.9.9.9"

    def test_falls_back_to_remote_addr_without_xff(self):
        ip = select_trusted_client_ip("", "192.168.1.1", trusted_hops=1)
        assert ip == "192.168.1.1"

    def test_falls_back_when_chain_shorter_than_trusted_hops(self):
        # Only one hop present but two proxies are trusted -> cannot trust it.
        ip = select_trusted_client_ip("9.9.9.9", "192.168.1.1", trusted_hops=2)
        assert ip == "192.168.1.1"

    def test_honours_multiple_trusted_hops(self):
        ip = select_trusted_client_ip("1.1.1.1, 2.2.2.2, 3.3.3.3", "10.0.0.1", trusted_hops=2)
        assert ip == "2.2.2.2"

    def test_malformed_selected_value_falls_back_to_remote_addr(self):
        ip = select_trusted_client_ip("9.9.9.9, not-an-ip", "192.168.1.1", trusted_hops=1)
        assert ip == "192.168.1.1"

    def test_returns_none_when_nothing_trustworthy(self):
        ip = select_trusted_client_ip("not-an-ip", None, trusted_hops=1)
        assert ip is None


# ---- get_request_id() ----


class TestGetRequestId:
    def test_uses_middleware_value(self, mock_request):
        mock_request.request_id = "middleware-id"
        assert get_request_id(mock_request) == "middleware-id"

    def test_uses_header_value(self, mock_request):
        result = get_request_id(mock_request)
        assert result == "req-abc-123"

    def test_generates_when_missing(self, mock_request_simple):
        result = get_request_id(mock_request_simple)
        assert len(result) == 8  # uuid4()[:8]
        int(result, 16)


# ---- get_actor_from_request() ----


class TestGetActorFromRequest:
    def test_authenticated_user(self, mock_request):
        actor_type, actor_id = get_actor_from_request(mock_request)
        assert actor_type == AuditLog.ActorType.USER
        assert actor_id is not None

    def test_apikey_auth(self, mock_apikey_request):
        actor_type, actor_id = get_actor_from_request(mock_apikey_request)
        assert actor_type == AuditLog.ActorType.APIKEY
        assert actor_id == 42

    def test_anonymous_returns_system(self, mock_request_simple):
        actor_type, actor_id = get_actor_from_request(mock_request_simple)
        assert actor_type == AuditLog.ActorType.SYSTEM
        assert actor_id is None
