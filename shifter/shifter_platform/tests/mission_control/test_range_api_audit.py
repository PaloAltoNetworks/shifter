"""Tests for Range API endpoints.

All tests mock the ORM — no @pytest.mark.django_db markers.
Views are called via RequestFactory with mock users; CMS/engine
service functions are patched at the view-module boundary.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.test import RequestFactory

from mission_control import views
from shared.enums import ResourceStatus
from shared.exceptions import CMSError
from shared.schemas import RangeContext

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rf():
    """Django RequestFactory (no DB needed)."""
    return RequestFactory()


@pytest.fixture
def mock_user():
    """Authenticated mock user."""
    user = MagicMock()
    user.id = 1
    user.pk = 1
    user.username = "rangetest"
    user.email = "rangetest@example.com"
    user.is_authenticated = True
    user.is_active = True
    return user


@pytest.fixture
def other_user():
    """A second authenticated mock user."""
    user = MagicMock()
    user.id = 2
    user.pk = 2
    user.username = "other"
    user.email = "other@example.com"
    user.is_authenticated = True
    user.is_active = True
    return user


@pytest.fixture
def mock_agent():
    """Mock AgentConfig object."""
    agent = MagicMock()
    agent.id = 10
    agent.name = "Test XDR Agent"
    agent.os = MagicMock()
    agent.os.slug = "windows"
    agent.os.name = "Windows"
    agent.file_size_mb = 47.7
    agent.original_filename = "agent.msi"
    agent.s3_key = "agents/test/fake.msi"
    agent.file_size_bytes = 50000000
    agent.sha256_hash = "abc123"
    return agent


@pytest.fixture
def mock_linux_agent():
    """Mock Linux AgentConfig object."""
    agent = MagicMock()
    agent.id = 20
    agent.name = "Linux Agent"
    agent.os = MagicMock()
    agent.os.slug = "linux-debian"
    agent.os.name = "Linux (Debian/Ubuntu)"
    agent.file_size_mb = 23.8
    agent.original_filename = "agent.deb"
    agent.s3_key = "agents/test/fake.deb"
    agent.file_size_bytes = 25000000
    agent.sha256_hash = "def456"
    return agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_range_context(user_id=1, **overrides):
    """Build a RangeContext with sensible defaults."""
    defaults = {
        "request_id": uuid4(),
        "range_id": 42,
        "user_id": user_id,
        "scenario_id": "basic",
        "status": ResourceStatus.READY,
        "instances": [],
        "agent_name": "Test XDR Agent",
    }
    defaults.update(overrides)
    return RangeContext(**defaults)


# ---------------------------------------------------------------------------
# TestGetRange
# ---------------------------------------------------------------------------


def _json(response):
    """Extract JSON from a JsonResponse."""
    import json

    return json.loads(response.content)


class TestRangeLifecycleAudit:
    """HTTP-layer audit entries for range lifecycle actions (#694).

    Verifies that each range lifecycle endpoint in mission_control records an
    AuditLog entry via risk_register.services.audit_log_from_request, carrying
    source IP / user agent / HTTP request_id alongside the action. The CMS
    service-layer audit calls are tested separately; these tests pin the
    HTTP boundary so the request context is not silently lost.
    """

    def test_launch_range_records_provision_audit(self, rf, mock_user, mock_agent):
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}, "scenario": "basic"}}',
            content_type="application/json",
        )
        request.user = mock_user
        range_ctx = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.PROVISIONING,
            agent_name=mock_agent.name,
        )

        with (
            patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]),
            patch.object(views, "cms_get_agent", return_value=mock_agent),
            patch.object(views, "cms_create_range", return_value=range_ctx),
            patch.object(views, "audit_log_from_request") as mock_audit,
        ):
            response = views.launch_range(request)

        assert response.status_code == 200
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["entity_type"] == views.AuditLog.EntityType.RANGE
        assert kwargs["action"] == views.AuditLog.Action.PROVISION
        assert kwargs["new_state"]["scenario"] == "basic"
        assert kwargs["new_state"]["request_id"] == str(range_ctx.request_id)

    def test_cancel_range_records_cancel_audit(self, rf, mock_user):
        request = rf.post(
            "/api/range/cancel/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch("cms.services.cancel_range"),
            patch.object(views, "audit_log_from_request") as mock_audit,
        ):
            response = views.cancel_range(request)

        assert response.status_code == 200
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["entity_type"] == views.AuditLog.EntityType.RANGE
        assert kwargs["entity_id"] == 42
        assert kwargs["action"] == views.AuditLog.Action.CANCEL

    def test_destroy_range_records_deprovision_audit(self, rf, mock_user):
        request = rf.post(
            "/api/range/destroy/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch("cms.services.destroy_range"),
            patch.object(views, "audit_log_from_request") as mock_audit,
        ):
            response = views.destroy_range(request)

        assert response.status_code == 200
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["entity_type"] == views.AuditLog.EntityType.RANGE
        assert kwargs["entity_id"] == 42
        assert kwargs["action"] == views.AuditLog.Action.DEPROVISION

    def test_pause_range_records_pause_audit(self, rf, mock_user):
        request = rf.post(
            "/api/range/pause/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch("cms.services.pause_range"),
            patch.object(views, "audit_log_from_request") as mock_audit,
        ):
            response = views.pause_range(request)

        assert response.status_code == 200
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["action"] == views.AuditLog.Action.PAUSE

    def test_resume_range_records_resume_audit(self, rf, mock_user):
        request = rf.post(
            "/api/range/resume/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch("cms.services.resume_range"),
            patch.object(views, "audit_log_from_request") as mock_audit,
        ):
            response = views.resume_range(request)

        assert response.status_code == 200
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["action"] == views.AuditLog.Action.RESUME

    def test_failed_destroy_does_not_audit(self, rf, mock_user):
        """If the CMS layer rejects the destroy, no audit entry is recorded."""
        request = rf.post(
            "/api/range/destroy/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch("cms.services.destroy_range", side_effect=CMSError("nope")),
            patch.object(views, "audit_log_from_request") as mock_audit,
        ):
            response = views.destroy_range(request)

        assert response.status_code == 400
        mock_audit.assert_not_called()

    def test_request_id_format_audits_against_uuid(self, rf, mock_user):
        """request_id (UUID) format threads the UUID into new_state."""
        request = rf.post(
            "/api/range/destroy/",
            data='{"request_id": "abc-123"}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch("cms.services.destroy_range_by_request_id"),
            patch.object(views, "audit_log_from_request") as mock_audit,
        ):
            response = views.destroy_range(request)

        assert response.status_code == 200
        kwargs = mock_audit.call_args.kwargs
        # entity_id falls back to 0 when only request_id is provided
        assert kwargs["entity_id"] == 0
        assert kwargs["new_state"]["request_id"] == "abc-123"
