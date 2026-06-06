"""Tests for Range API endpoints.

All tests mock the ORM — no @pytest.mark.django_db markers.
Views are called via RequestFactory with mock users; CMS/engine
service functions are patched at the view-module boundary.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import AnonymousUser
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


class TestGetRange:
    """Tests for get_range view.

    The view consumes RangeContext from cms.get_active_range().
    """

    def test_requires_login(self, rf):
        request = rf.get("/api/range/")
        request.user = AnonymousUser()
        response = views.get_range(request)
        assert response.status_code == 302  # Redirect to login

    def test_returns_no_range_when_none_exists(self, rf, mock_user):
        request = rf.get("/api/range/")
        request.user = mock_user

        with patch.object(views, "get_active_range", return_value=None):
            response = views.get_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["has_range"] is False
        assert data["range"] is None

    def test_returns_active_range(self, rf, mock_user):
        request = rf.get("/api/range/")
        request.user = mock_user

        mock_range_context = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.READY,
        )

        with patch.object(views, "get_active_range", return_value=mock_range_context):
            response = views.get_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["has_range"] is True
        assert data["range"]["range_id"] == 42
        assert data["range"]["status"] == "ready"
        assert data["range"]["agent_name"] == "Test XDR Agent"
        assert data["range"]["scenario_id"] == "basic"
        assert data["range"]["is_ready"] is True
        assert data["range"]["is_terminal"] is False
        assert data["range"]["is_active"] is True

    def test_returns_provisioning_range(self, rf, mock_user):
        """Test range in provisioning state has correct computed properties."""
        request = rf.get("/api/range/")
        request.user = mock_user

        mock_range_context = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.PROVISIONING,
            agent_name="Test Agent",
        )

        with patch.object(views, "get_active_range", return_value=mock_range_context):
            response = views.get_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["has_range"] is True
        assert data["range"]["status"] == "provisioning"
        assert data["range"]["is_ready"] is False
        assert data["range"]["is_terminal"] is False
        assert data["range"]["is_active"] is True

    def test_returns_destroying_range(self, rf, mock_user):
        """Test range in destroying state has correct computed properties."""
        request = rf.get("/api/range/")
        request.user = mock_user

        mock_range_context = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.DESTROYING,
            agent_name="Test Agent",
        )

        with patch.object(views, "get_active_range", return_value=mock_range_context):
            response = views.get_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["has_range"] is True
        assert data["range"]["status"] == "destroying"
        assert data["range"]["is_ready"] is False
        assert data["range"]["is_terminal"] is False
        assert data["range"]["is_active"] is True


class TestLaunchRange:
    def test_requires_login(self, rf):
        request = rf.post(
            "/api/range/launch/",
            data="{}",
            content_type="application/json",
        )
        request.user = AnonymousUser()
        response = views.launch_range(request)
        assert response.status_code == 302

    def test_requires_agent_id(self, rf, mock_user):
        request = rf.post(
            "/api/range/launch/",
            data="{}",
            content_type="application/json",
        )
        request.user = mock_user

        with patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]):
            response = views.launch_range(request)

        assert response.status_code == 400
        assert "agent_id" in _json(response)["error"] or "agents" in _json(response)["error"]

    def test_rejects_nonexistent_agent(self, rf, mock_user):
        request = rf.post(
            "/api/range/launch/",
            data='{"agent_id": 99999}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]),
            patch.object(views, "cms_get_agent", side_effect=CMSError("Agent not found")),
        ):
            response = views.launch_range(request)

        assert response.status_code == 400

    def test_successful_launch(self, rf, mock_user, mock_agent):
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}}}',
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
        ):
            response = views.launch_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        assert data["range"]["status"] == "provisioning"
        assert data["range"]["agent_name"] == mock_agent.name

    def test_successful_launch_with_ecs(self, rf, mock_user, mock_agent):
        """Test launch delegates to CMS service (ECS details are internal)."""
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}}}',
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
            patch.object(views, "cms_create_range", return_value=range_ctx) as mock_create,
        ):
            response = views.launch_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        assert data["range"]["status"] == "provisioning"
        # Verify cms_create_range was called with correct args
        mock_create.assert_called_once_with(mock_user, "basic", {"windows": mock_agent.id})

    def test_rejects_when_range_exists(self, rf, mock_user, mock_agent):
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}}}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]),
            patch.object(views, "cms_get_agent", return_value=mock_agent),
            patch.object(
                views,
                "cms_create_range",
                side_effect=CMSError("You already have an active range"),
            ),
        ):
            response = views.launch_range(request)

        assert response.status_code == 400
        assert "already have an active range" in _json(response)["error"]

    def test_ad_scenario_requires_windows_agent_for_dc(self, rf, mock_user, mock_linux_agent):
        """AD scenario requires Windows agent for DC.
        Linux-only agent is insufficient because DC needs Windows agent.
        """
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_linux_agent.id}, "scenario": "ad_attack_lab"}}',
            content_type="application/json",
        )
        request.user = mock_user

        with (
            patch.object(
                views,
                "cms_list_scenarios",
                return_value=[{"id": "basic"}, {"id": "ad_attack_lab"}],
            ),
            patch.object(views, "cms_get_agent", return_value=mock_linux_agent),
            patch.object(
                views,
                "cms_create_range",
                side_effect=CMSError("AD scenario requires a Windows agent for the DC"),
            ),
        ):
            response = views.launch_range(request)

        assert response.status_code == 400

    def test_ad_scenario_success_with_windows_agent(self, rf, mock_user, mock_agent):
        """AD scenario succeeds with Windows agent."""
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}, "scenario": "ad_attack_lab"}}',
            content_type="application/json",
        )
        request.user = mock_user

        range_ctx = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.PROVISIONING,
            scenario_id="ad_attack_lab",
        )

        with (
            patch.object(
                views,
                "cms_list_scenarios",
                return_value=[{"id": "basic"}, {"id": "ad_attack_lab"}],
            ),
            patch.object(views, "cms_get_agent", return_value=mock_agent),
            patch.object(views, "cms_create_range", return_value=range_ctx),
        ):
            response = views.launch_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        assert data["range"]["status"] == "provisioning"
        assert data["range"]["scenario_id"] == "ad_attack_lab"

    def test_basic_scenario_allows_any_agent(self, rf, mock_user, mock_linux_agent):
        """Basic scenario works with any agent OS."""
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_linux_agent.id}, "scenario": "basic"}}',
            content_type="application/json",
        )
        request.user = mock_user

        range_ctx = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.PROVISIONING,
            scenario_id="basic",
        )

        with (
            patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]),
            patch.object(views, "cms_get_agent", return_value=mock_linux_agent),
            patch.object(views, "cms_create_range", return_value=range_ctx),
        ):
            response = views.launch_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        assert data["range"]["scenario_id"] == "basic"


class TestCancelRange:
    """Tests for cancel_range view.

    The view requires range_id in the request body and delegates to
    cms.cancel_range() which updates status to DESTROYED and calls engine.
    """

    def test_requires_login(self, rf):
        request = rf.post(
            "/api/range/cancel/",
            data="{}",
            content_type="application/json",
        )
        request.user = AnonymousUser()
        response = views.cancel_range(request)
        assert response.status_code == 302

    def test_requires_range_id_in_body(self, rf, mock_user):
        """Request must include range_id in JSON body."""
        request = rf.post(
            "/api/range/cancel/",
            data="{}",
            content_type="application/json",
        )
        request.user = mock_user
        response = views.cancel_range(request)
        assert response.status_code == 400
        assert "range_id" in _json(response)["error"]

    def test_returns_error_when_range_not_found(self, rf, mock_user):
        """Returns error when range_id doesn't exist."""
        request = rf.post(
            "/api/range/cancel/",
            data='{"range_id": 99999}',
            content_type="application/json",
        )
        request.user = mock_user

        # View does `from cms import cancel_range` locally — mock at source
        with patch(
            "cms.services.cancel_range",
            side_effect=CMSError("Range not found"),
        ):
            response = views.cancel_range(request)

        assert response.status_code == 400

    def test_successful_cancel(self, rf, mock_user):
        """Successfully cancels a range by setting status to DESTROYED."""
        request = rf.post(
            "/api/range/cancel/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with patch(
            "cms.services.cancel_range",
        ) as mock_cancel:
            response = views.cancel_range(request)

        assert response.status_code == 200
        assert _json(response)["success"] is True
        mock_cancel.assert_called_once_with(mock_user, 42)

    def test_cancel_delegates_to_cms(self, rf, mock_user):
        """Cancel calls CMS cancel_range which handles status + engine call."""
        request = rf.post(
            "/api/range/cancel/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with patch("cms.services.cancel_range") as mock_cancel:
            views.cancel_range(request)

        mock_cancel.assert_called_once_with(mock_user, 42)

    def test_cannot_cancel_other_users_range(self, rf, other_user):
        """Users cannot cancel ranges they don't own."""
        request = rf.post(
            "/api/range/cancel/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = other_user

        with patch(
            "cms.services.cancel_range",
            side_effect=CMSError("Range not found"),
        ):
            response = views.cancel_range(request)

        assert response.status_code == 400


class TestDestroyRange:
    def test_requires_login(self, rf):
        request = rf.post(
            "/api/range/destroy/",
            data="{}",
            content_type="application/json",
        )
        request.user = AnonymousUser()
        response = views.destroy_range(request)
        assert response.status_code == 302

    def test_returns_error_when_no_range(self, rf, mock_user):
        request = rf.post(
            "/api/range/destroy/",
            data='{"range_id": 99999}',
            content_type="application/json",
        )
        request.user = mock_user

        with patch(
            "cms.services.destroy_range",
            side_effect=CMSError("Range not found"),
        ):
            response = views.destroy_range(request)

        assert response.status_code == 400

    def test_successful_destroy(self, rf, mock_user):
        request = rf.post(
            "/api/range/destroy/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with patch("cms.services.destroy_range") as mock_destroy:
            response = views.destroy_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        mock_destroy.assert_called_once_with(mock_user, 42)

    def test_can_destroy_failed_range(self, rf, mock_user):
        """Failed ranges can be destroyed to clean up."""
        request = rf.post(
            "/api/range/destroy/",
            data='{"range_id": 42}',
            content_type="application/json",
        )
        request.user = mock_user

        with patch("cms.services.destroy_range") as mock_destroy:
            response = views.destroy_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        mock_destroy.assert_called_once_with(mock_user, 42)


class TestLaunchRangeWhileDestroying:
    """Test that users CAN launch while a range is being destroyed."""

    def test_can_launch_while_destroying(self, rf, mock_user, mock_agent):
        """User can launch a new range while old one is being cleaned up.

        The CMS service handles subnet allocation internally — the view
        just delegates to cms_create_range which succeeds if allowed.
        """
        request = rf.post(
            "/api/range/launch/",
            data=f'{{"agent_id": {mock_agent.id}}}',
            content_type="application/json",
        )
        request.user = mock_user

        range_ctx = _make_range_context(
            user_id=mock_user.id,
            status=ResourceStatus.PROVISIONING,
        )

        with (
            patch.object(views, "cms_list_scenarios", return_value=[{"id": "basic"}]),
            patch.object(views, "cms_get_agent", return_value=mock_agent),
            patch.object(views, "cms_create_range", return_value=range_ctx),
        ):
            response = views.launch_range(request)

        assert response.status_code == 200
        data = _json(response)
        assert data["success"] is True
        assert data["range"]["status"] == "provisioning"
