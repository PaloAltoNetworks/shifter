"""Tests for risk_register.services audit logging functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User

from risk_register.models import AuditLog
from risk_register.services import (
    audit_auth_event,
    audit_log,
    audit_log_from_request,
    audit_log_system_event,
    audit_session_event,
    get_actor_from_request,
    get_client_ip,
    get_request_id,
)

# ---- Fixtures ----


@pytest.fixture
def staff_user(db):
    """Create a saved staff user."""
    return User.objects.create_user(  # nosec B106
        username="testuser",
        email="test@example.com",
        password="testpass",  # noqa: S106
    )


@pytest.fixture
def mock_request(staff_user):
    """Mock Django HttpRequest with authenticated user."""
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
    """Mock request with only REMOTE_ADDR (no XFF, no auth)."""
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
    """Mock request with API key authentication."""
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
        assert entry is not None
        assert entry.entity_type == AuditLog.EntityType.RANGE
        assert entry.entity_id == 42
        assert entry.action == AuditLog.Action.CREATE
        assert entry.actor_type == AuditLog.ActorType.USER
        assert entry.actor_id == staff_user.id
        assert entry.new_state == {"scenario": "test"}
        assert entry.context == "test context"
        assert entry.source_ip == "10.0.0.1"
        assert entry.user_agent == "TestAgent"
        assert entry.request_id == "req-123"

    @patch("risk_register.services.AuditLog.log", side_effect=Exception("DB error"))
    def test_returns_none_on_db_failure(self, mock_log):
        result = audit_log(
            entity_type=AuditLog.EntityType.RANGE,
            entity_id=1,
            action=AuditLog.Action.CREATE,
        )
        assert result is None


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
        assert entry.actor_type == AuditLog.ActorType.USER
        assert entry.actor_id == staff_user.id
        assert entry.source_ip == "10.0.0.1"
        assert entry.user_agent == "TestBrowser/1.0"
        assert entry.request_id == "req-abc-123"

    def test_handles_apikey_auth(self, mock_apikey_request):
        with patch("risk_register.services.AuditLog.log") as mock_log:
            mock_log.return_value = MagicMock()
            audit_log_from_request(
                mock_apikey_request,
                entity_type=AuditLog.EntityType.RANGE,
                entity_id=1,
                action=AuditLog.Action.CREATE,
            )
            call_kwargs = mock_log.call_args.kwargs
            assert call_kwargs["actor_type"] == AuditLog.ActorType.APIKEY
            assert call_kwargs["actor_id"] == 42


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
            user_id=staff_user.id,
            email="test@example.com",
            cognito_sub="abc-123",
            source_ip="10.0.0.1",
            user_agent="Browser/1.0",
        )
        assert entry is not None
        assert entry.action == AuditLog.Action.LOGIN
        assert entry.entity_type == AuditLog.EntityType.USER
        assert entry.new_state == {"email": "test@example.com", "cognito_sub": "abc-123"}
        assert entry.actor_type == AuditLog.ActorType.COGNITO


# ---- audit_session_event() ----


@pytest.mark.django_db
class TestAuditSessionEvent:
    def test_records_connect_event(self, staff_user):
        entry = audit_session_event(
            action=AuditLog.Action.CONNECT,
            user_id=staff_user.id,
            session_id="sess-abc",
            range_id=42,
            session_type="terminal",
            target_ip="172.16.0.5",
            source_ip="10.0.0.1",
        )
        assert entry is not None
        assert entry.action == AuditLog.Action.CONNECT
        assert entry.entity_type == AuditLog.EntityType.SESSION
        assert entry.new_state["session_id"] == "sess-abc"
        assert entry.new_state["range_id"] == 42
        assert entry.new_state["session_type"] == "terminal"
        assert entry.new_state["target_ip"] == "172.16.0.5"


# ---- get_client_ip() ----


class TestGetClientIp:
    def test_xff_first_ip(self, mock_request):
        ip = get_client_ip(mock_request)
        assert ip == "10.0.0.1"

    def test_remote_addr_fallback(self, mock_request_simple):
        ip = get_client_ip(mock_request_simple)
        assert ip == "192.168.1.1"


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
