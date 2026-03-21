"""Tests for launch_range view wiring to cms_create_range.

All tests mock the ORM -- no @pytest.mark.django_db markers.
Views are called via RequestFactory with mock users; CMS service
functions are patched at the view-module boundary.

Verifies that launch_range:
- Validates inputs (agent_id required, JSON format)
- Uses CMS for scenario validation
- Calls cms_create_range and returns RangeContext dict
- Handles CMSError appropriately
- Logs successful launches
"""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.test import RequestFactory

from mission_control import views
from shared.enums import ResourceStatus
from shared.exceptions import CMSError
from shared.schemas import InstanceContext, RangeContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(response):
    """Extract JSON from a JsonResponse."""
    return json.loads(response.content)


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
    user.username = "test@example.com"
    user.email = "test@example.com"
    user.is_authenticated = True
    user.is_active = True
    return user


@pytest.fixture
def mock_windows_agent():
    """Mock Windows AgentConfig object."""
    agent = MagicMock()
    agent.id = 10
    agent.name = "Windows Agent"
    agent.os = MagicMock()
    agent.os.slug = "windows"
    agent.os.name = "Windows"
    agent.original_filename = "cortex_agent.msi"
    agent.s3_key = "agents/123/agent.msi"
    agent.file_size_bytes = 5000000
    agent.sha256_hash = "abc123def456"
    return agent


@pytest.fixture
def mock_cms_list_scenarios():
    """Mock CMS list_scenarios to return basic and ad_attack_lab."""
    scenarios = [
        {"id": "basic", "name": "Basic"},
        {"id": "ad_attack_lab", "name": "AD Attack Lab"},
    ]
    with patch.object(views, "cms_list_scenarios", return_value=scenarios):
        yield scenarios


@pytest.fixture
def mock_cms_get_agent(mock_windows_agent):
    """Mock CMS get_agent to return the mock Windows agent."""
    with patch.object(views, "cms_get_agent", return_value=mock_windows_agent) as mock_get:
        yield mock_get


@pytest.fixture
def mock_range_context():
    """Create a mock RangeContext for testing."""
    return RangeContext(
        request_id=uuid4(),
        range_id=42,
        scenario_id="basic",
        user_id=1,
        status=ResourceStatus.PROVISIONING,
        instances=[
            InstanceContext(role="attacker", os_type="kali"),
            InstanceContext(role="victim", os_type="windows"),
        ],
        agent_name="Windows Agent",
    )


# -----------------------------------------------------------------------------
# Input validation tests
# -----------------------------------------------------------------------------


class TestLaunchRangeInputValidation:
    """Tests for input validation in launch_range view."""

    def test_returns_400_for_invalid_json(self, rf, mock_user):
        """View returns 400 when request body is not valid JSON."""
        request = rf.post(
            "/api/range/launch/",
            data="not valid json{",
            content_type="application/json",
        )
        request.user = mock_user

        response = views.launch_range(request)
        assert response.status_code == 400
        assert _json(response)["error"] == "Invalid JSON"

    def test_returns_400_for_empty_body(self, rf, mock_user):
        """View returns 400 when request body is empty."""
        request = rf.post(
            "/api/range/launch/",
            data="",
            content_type="application/json",
        )
        request.user = mock_user

        response = views.launch_range(request)
        assert response.status_code == 400
        assert _json(response)["error"] == "Invalid JSON"

    def test_returns_400_when_agent_id_missing(self, rf, mock_user, mock_cms_list_scenarios):
        """View returns 400 when agent_id is not provided."""
        request = rf.post(
            "/api/range/launch/",
            data=json.dumps({"scenario": "basic"}),
            content_type="application/json",
        )
        request.user = mock_user

        response = views.launch_range(request)
        assert response.status_code == 400
        assert "agent_id" in _json(response)["error"]

    def test_returns_400_when_agent_id_is_null(self, rf, mock_user, mock_cms_list_scenarios):
        """View returns 400 when agent_id is explicitly null."""
        request = rf.post(
            "/api/range/launch/",
            data=json.dumps({"agent_id": None, "scenario": "basic"}),
            content_type="application/json",
        )
        request.user = mock_user

        response = views.launch_range(request)
        assert response.status_code == 400
        assert "agent_id" in _json(response)["error"]

    def test_returns_400_when_agent_id_is_zero(self, rf, mock_user, mock_cms_list_scenarios):
        """View returns 400 when agent_id is zero (falsy)."""
        request = rf.post(
            "/api/range/launch/",
            data=json.dumps({"agent_id": 0, "scenario": "basic"}),
            content_type="application/json",
        )
        request.user = mock_user

        response = views.launch_range(request)
        assert response.status_code == 400
        assert "agent_id" in _json(response)["error"]


# -----------------------------------------------------------------------------
# Scenario validation tests
# -----------------------------------------------------------------------------


class TestLaunchRangeScenarioValidation:
    """Tests for scenario validation in launch_range view."""

    def test_accepts_basic_scenario(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """View accepts 'basic' scenario."""
        with patch.object(views, "cms_create_range", return_value=mock_range_context):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id, "scenario": "basic"}),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            assert response.status_code == 200

    def test_accepts_ad_attack_lab_scenario(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """View accepts 'ad_attack_lab' scenario."""
        with patch.object(views, "cms_create_range", return_value=mock_range_context):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps(
                    {
                        "agent_id": mock_windows_agent.id,
                        "scenario": "ad_attack_lab",
                    }
                ),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            assert response.status_code == 200

    def test_rejects_unknown_scenario(self, rf, mock_user, mock_windows_agent, mock_cms_get_agent):
        """View rejects unknown scenario with 400 error."""
        with patch.object(
            views,
            "cms_list_scenarios",
            return_value=[{"id": "basic", "name": "Basic"}],
        ):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps(
                    {
                        "agent_id": mock_windows_agent.id,
                        "scenario": "unknown_scenario",
                    }
                ),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            assert response.status_code == 400
            assert "Invalid" in _json(response)["error"]

    def test_scenario_validation_uses_cms(self, rf, mock_user, mock_windows_agent, mock_cms_get_agent):
        """Scenario validation uses CMS list_scenarios, not hardcoded list."""
        mock_scenarios = [{"id": "basic", "name": "Basic"}]

        with patch.object(views, "cms_list_scenarios", return_value=mock_scenarios):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps(
                    {
                        "agent_id": mock_windows_agent.id,
                        "scenario": "ad_attack_lab",
                    }
                ),
                content_type="application/json",
            )
            request.user = mock_user

            # ad_attack_lab should be rejected since CMS doesn't list it
            response = views.launch_range(request)
            assert response.status_code == 400

    def test_defaults_to_basic_scenario(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """View defaults to 'basic' scenario when not specified."""
        with patch.object(views, "cms_create_range", return_value=mock_range_context) as mock_create:
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id}),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            assert response.status_code == 200
            # Verify basic was passed to cms_create_range
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            assert call_args[0][1] == "basic"  # scenario is 2nd positional arg


# -----------------------------------------------------------------------------
# Success behavior tests
# -----------------------------------------------------------------------------


class TestLaunchRangeSuccess:
    """Tests for successful launch_range behavior."""

    def test_returns_success_with_range_context_dict(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """Successful launch returns success=True and range as dict."""
        with patch.object(views, "cms_create_range", return_value=mock_range_context):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id, "scenario": "basic"}),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            assert response.status_code == 200
            data = _json(response)
            assert data["success"] is True
            assert "range" in data
            assert isinstance(data["range"], dict)

    def test_range_dict_contains_expected_fields(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """Range dict contains RangeContext fields."""
        with patch.object(views, "cms_create_range", return_value=mock_range_context):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id, "scenario": "basic"}),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            data = _json(response)
            range_data = data["range"]

            # Verify RangeContext fields are present
            assert range_data["range_id"] == 42
            assert range_data["scenario_id"] == "basic"
            assert range_data["user_id"] == 1
            assert range_data["status"] == "provisioning"
            assert range_data["agent_name"] == "Windows Agent"
            assert isinstance(range_data["instances"], list)
            assert len(range_data["instances"]) == 2

    def test_range_dict_contains_computed_fields(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """Range dict includes computed fields from RangeContext."""
        with patch.object(views, "cms_create_range", return_value=mock_range_context):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id}),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            data = _json(response)
            range_data = data["range"]

            # Computed fields should be present
            assert range_data["is_ready"] is False  # PROVISIONING != READY
            assert range_data["is_terminal"] is False  # Not DESTROYED/FAILED
            assert range_data["is_active"] is True  # Not terminal

    def test_calls_cms_create_range_with_correct_args(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """launch_range passes correct arguments to cms_create_range."""
        with patch.object(views, "cms_create_range", return_value=mock_range_context) as mock_create:
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps(
                    {
                        "agent_id": mock_windows_agent.id,
                        "scenario": "ad_attack_lab",
                    }
                ),
                content_type="application/json",
            )
            request.user = mock_user

            views.launch_range(request)

            mock_create.assert_called_once()
            call_args = mock_create.call_args

            # Verify positional args: (user, scenario, agents_by_os)
            assert call_args[0][0].email == mock_user.email  # User object
            assert call_args[0][1] == "ad_attack_lab"  # scenario
            assert call_args[0][2] == {"windows": mock_windows_agent.id}  # agents_by_os


# -----------------------------------------------------------------------------
# Error handling tests
# -----------------------------------------------------------------------------


class TestLaunchRangeErrorHandling:
    """Tests for error handling in launch_range view."""

    def test_returns_400_on_cms_error(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
    ):
        """View returns 400 when cms_create_range raises CMSError."""
        with patch.object(
            views,
            "cms_create_range",
            side_effect=CMSError("Agent not found"),
        ):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id, "scenario": "basic"}),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            assert response.status_code == 400
            assert _json(response)["error"] == "Agent not found"

    def test_cms_error_message_passed_to_response(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
    ):
        """CMSError message is included in error response."""
        error_message = "User already has an active range"
        with patch.object(
            views,
            "cms_create_range",
            side_effect=CMSError(error_message),
        ):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id, "scenario": "basic"}),
                content_type="application/json",
            )
            request.user = mock_user

            response = views.launch_range(request)
            assert _json(response)["error"] == error_message


# -----------------------------------------------------------------------------
# Logging tests
# -----------------------------------------------------------------------------


class TestLaunchRangeLogging:
    """Tests for logging in launch_range view."""

    def test_logs_info_on_successful_launch(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
        mock_range_context,
    ):
        """View logs INFO on successful launch."""
        with (
            patch.object(views, "cms_create_range", return_value=mock_range_context),
            patch.object(views, "logger") as mock_logger,
        ):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id, "scenario": "basic"}),
                content_type="application/json",
            )
            request.user = mock_user

            views.launch_range(request)
            mock_logger.info.assert_called_once()

    def test_no_log_on_validation_failure(self, rf, mock_user):
        """View does not log INFO when validation fails."""
        with patch.object(views, "logger") as mock_logger:
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"scenario": "basic"}),  # Missing agent_id
                content_type="application/json",
            )
            request.user = mock_user

            with patch.object(
                views,
                "cms_list_scenarios",
                return_value=[{"id": "basic", "name": "Basic"}],
            ):
                views.launch_range(request)

            mock_logger.info.assert_not_called()

    def test_no_log_on_cms_error(
        self,
        rf,
        mock_user,
        mock_windows_agent,
        mock_cms_list_scenarios,
        mock_cms_get_agent,
    ):
        """View does not log INFO when CMSError occurs."""
        with (
            patch.object(
                views,
                "cms_create_range",
                side_effect=CMSError("Test error"),
            ),
            patch.object(views, "logger") as mock_logger,
        ):
            request = rf.post(
                "/api/range/launch/",
                data=json.dumps({"agent_id": mock_windows_agent.id, "scenario": "basic"}),
                content_type="application/json",
            )
            request.user = mock_user

            views.launch_range(request)
            mock_logger.info.assert_not_called()
