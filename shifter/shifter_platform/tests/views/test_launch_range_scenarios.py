"""Tests for launch_range view wiring to cms_create_range.

Verifies that launch_range:
- Validates inputs (agent_id required, JSON format)
- Uses CMS for scenario validation
- Calls cms_create_range and returns RangeContext dict
- Handles CMSError appropriately
- Logs successful launches
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from cms.models import AgentConfig, OperatingSystem
from shared.enums import RangeStatus

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="test@example.com",
        email="test@example.com",
        password="testpass",
    )


@pytest.fixture
def client(user):
    c = Client()
    c.login(username="test@example.com", password="testpass")
    return c


@pytest.fixture
def windows_agent(user, db):
    """Windows agent for testing."""
    os = OperatingSystem.objects.get(slug="windows")
    return AgentConfig.objects.create(
        user=user,
        name="Windows Agent",
        os=os,
        s3_key="agents/123/agent.msi",
        original_filename="cortex_agent.msi",
        file_size_bytes=5000000,
        sha256_hash="abc123def456",
    )


@pytest.fixture
def mock_cms_list_scenarios():
    """Mock CMS list_scenarios to return basic and ad_attack_lab."""
    scenarios = [
        {"id": "basic", "name": "Basic"},
        {"id": "ad_attack_lab", "name": "AD Attack Lab"},
    ]
    with patch(
        "mission_control.views.cms_list_scenarios", return_value=scenarios
    ):
        yield scenarios


@pytest.fixture
def mock_range_context():
    """Create a mock RangeContext for testing."""
    from shared.schemas import InstanceContext, RangeContext

    return RangeContext(
        range_id=42,
        scenario_id="basic",
        user_id=1,
        status=RangeStatus.PROVISIONING,
        instances=[
            InstanceContext(role="attacker", os_type="kali"),
            InstanceContext(role="victim", os_type="windows"),
        ],
        agent_name="Windows Agent",
    )


# -----------------------------------------------------------------------------
# Input validation tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaunchRangeInputValidation:
    """Tests for input validation in launch_range view."""

    def test_returns_400_for_invalid_json(self, client):
        """View returns 400 when request body is not valid JSON."""
        url = reverse("mission_control:launch_range")
        response = client.post(
            url,
            data="not valid json{",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Invalid JSON"

    def test_returns_400_for_empty_body(self, client):
        """View returns 400 when request body is empty."""
        url = reverse("mission_control:launch_range")
        response = client.post(
            url,
            data="",
            content_type="application/json",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "Invalid JSON"

    def test_returns_400_when_agent_id_missing(
        self, client, mock_cms_list_scenarios
    ):
        """View returns 400 when agent_id is not provided."""
        url = reverse("mission_control:launch_range")
        response = client.post(
            url,
            data={"scenario": "basic"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "agent_id" in response.json()["error"]

    def test_returns_400_when_agent_id_is_null(
        self, client, mock_cms_list_scenarios
    ):
        """View returns 400 when agent_id is explicitly null."""
        url = reverse("mission_control:launch_range")
        response = client.post(
            url,
            data={"agent_id": None, "scenario": "basic"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "agent_id" in response.json()["error"]

    def test_returns_400_when_agent_id_is_zero(
        self, client, mock_cms_list_scenarios
    ):
        """View returns 400 when agent_id is zero (falsy)."""
        url = reverse("mission_control:launch_range")
        response = client.post(
            url,
            data={"agent_id": 0, "scenario": "basic"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "agent_id" in response.json()["error"]


# -----------------------------------------------------------------------------
# Scenario validation tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaunchRangeScenarioValidation:
    """Tests for scenario validation in launch_range view."""

    def test_accepts_basic_scenario(
        self, client, windows_agent, mock_cms_list_scenarios, mock_range_context
    ):
        """View accepts 'basic' scenario."""
        with patch(
            "mission_control.views.cms_create_range",
            return_value=mock_range_context,
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "basic"},
                content_type="application/json",
            )
            assert response.status_code == 200

    def test_accepts_ad_attack_lab_scenario(
        self, client, windows_agent, mock_cms_list_scenarios, mock_range_context
    ):
        """View accepts 'ad_attack_lab' scenario."""
        with patch(
            "mission_control.views.cms_create_range",
            return_value=mock_range_context,
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "ad_attack_lab"},
                content_type="application/json",
            )
            assert response.status_code == 200

    def test_rejects_unknown_scenario(self, client, windows_agent):
        """View rejects unknown scenario with 400 error."""
        # Mock CMS to return only basic
        with patch(
            "mission_control.views.cms_list_scenarios",
            return_value=[{"id": "basic", "name": "Basic"}],
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={
                    "agent_id": windows_agent.id,
                    "scenario": "unknown_scenario",
                },
                content_type="application/json",
            )
            assert response.status_code == 400
            assert "Invalid" in response.json()["error"]

    def test_scenario_validation_uses_cms(self, client, windows_agent):
        """Scenario validation uses CMS list_scenarios, not hardcoded list."""
        # Mock CMS to return only 'basic' as valid
        mock_scenarios = [{"id": "basic", "name": "Basic"}]

        with patch(
            "mission_control.views.cms_list_scenarios",
            return_value=mock_scenarios,
        ):
            url = reverse("mission_control:launch_range")

            # ad_attack_lab should be rejected since CMS doesn't list it
            response = client.post(
                url,
                data={
                    "agent_id": windows_agent.id,
                    "scenario": "ad_attack_lab",
                },
                content_type="application/json",
            )
            # If CMS is being used, ad_attack_lab should be invalid
            assert response.status_code == 400

    def test_defaults_to_basic_scenario(
        self, client, windows_agent, mock_cms_list_scenarios, mock_range_context
    ):
        """View defaults to 'basic' scenario when not specified."""
        with patch(
            "mission_control.views.cms_create_range",
            return_value=mock_range_context,
        ) as mock_create:
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id},
                content_type="application/json",
            )
            assert response.status_code == 200
            # Verify basic was passed to cms_create_range
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            assert call_args[0][1] == "basic"  # scenario is 2nd positional arg


# -----------------------------------------------------------------------------
# Success behavior tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaunchRangeSuccess:
    """Tests for successful launch_range behavior."""

    def test_returns_success_with_range_context_dict(
        self, client, windows_agent, mock_cms_list_scenarios, mock_range_context
    ):
        """Successful launch returns success=True and range as dict."""
        with patch(
            "mission_control.views.cms_create_range",
            return_value=mock_range_context,
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "basic"},
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "range" in data
            assert isinstance(data["range"], dict)

    def test_range_dict_contains_expected_fields(
        self, client, windows_agent, mock_cms_list_scenarios, mock_range_context
    ):
        """Range dict contains RangeContext fields."""
        with patch(
            "mission_control.views.cms_create_range",
            return_value=mock_range_context,
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "basic"},
                content_type="application/json",
            )

            data = response.json()
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
        self, client, windows_agent, mock_cms_list_scenarios, mock_range_context
    ):
        """Range dict includes computed fields from RangeContext."""
        with patch(
            "mission_control.views.cms_create_range",
            return_value=mock_range_context,
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id},
                content_type="application/json",
            )

            data = response.json()
            range_data = data["range"]

            # Computed fields should be present
            assert range_data["is_ready"] is False  # PROVISIONING != READY
            assert range_data["is_terminal"] is False  # Not DESTROYED/FAILED
            assert range_data["is_active"] is True  # Not terminal

    def test_calls_cms_create_range_with_correct_args(
        self,
        client,
        user,
        windows_agent,
        mock_cms_list_scenarios,
        mock_range_context,
    ):
        """launch_range passes correct arguments to cms_create_range."""
        with patch(
            "mission_control.views.cms_create_range",
            return_value=mock_range_context,
        ) as mock_create:
            url = reverse("mission_control:launch_range")
            client.post(
                url,
                data={
                    "agent_id": windows_agent.id,
                    "scenario": "ad_attack_lab",
                },
                content_type="application/json",
            )

            mock_create.assert_called_once()
            call_args = mock_create.call_args

            # Verify positional args: (user, scenario, agent_id)
            assert call_args[0][0].email == user.email  # User object
            assert call_args[0][1] == "ad_attack_lab"  # scenario
            assert call_args[0][2] == windows_agent.id  # agent_id


# -----------------------------------------------------------------------------
# Error handling tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaunchRangeErrorHandling:
    """Tests for error handling in launch_range view."""

    def test_returns_400_on_cms_error(
        self, client, windows_agent, mock_cms_list_scenarios
    ):
        """View returns 400 when cms_create_range raises CMSError."""
        from cms.exceptions import CMSError

        with patch(
            "mission_control.views.cms_create_range",
            side_effect=CMSError("Agent not found"),
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "basic"},
                content_type="application/json",
            )

            assert response.status_code == 400
            assert response.json()["error"] == "Agent not found"

    def test_cms_error_message_passed_to_response(
        self, client, windows_agent, mock_cms_list_scenarios
    ):
        """CMSError message is included in error response."""
        from cms.exceptions import CMSError

        error_message = "User already has an active range"
        with patch(
            "mission_control.views.cms_create_range",
            side_effect=CMSError(error_message),
        ):
            url = reverse("mission_control:launch_range")
            response = client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "basic"},
                content_type="application/json",
            )

            assert response.json()["error"] == error_message


# -----------------------------------------------------------------------------
# Logging tests
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaunchRangeLogging:
    """Tests for logging in launch_range view."""

    def test_logs_info_on_successful_launch(
        self,
        client,
        user,
        windows_agent,
        mock_cms_list_scenarios,
        mock_range_context,
    ):
        """View logs INFO on successful launch."""
        with (
            patch(
                "mission_control.views.cms_create_range",
                return_value=mock_range_context,
            ),
            patch("mission_control.views.logger") as mock_logger,
        ):
            url = reverse("mission_control:launch_range")
            client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "basic"},
                content_type="application/json",
            )

            mock_logger.info.assert_called_once()

    def test_no_log_on_validation_failure(self, client, windows_agent):
        """View does not log INFO when validation fails."""
        with patch("mission_control.views.logger") as mock_logger:
            url = reverse("mission_control:launch_range")
            client.post(
                url,
                data={"scenario": "basic"},  # Missing agent_id
                content_type="application/json",
            )

            mock_logger.info.assert_not_called()

    def test_no_log_on_cms_error(
        self, client, windows_agent, mock_cms_list_scenarios
    ):
        """View does not log INFO when CMSError occurs."""
        from cms.exceptions import CMSError

        with (
            patch(
                "mission_control.views.cms_create_range",
                side_effect=CMSError("Test error"),
            ),
            patch("mission_control.views.logger") as mock_logger,
        ):
            url = reverse("mission_control:launch_range")
            client.post(
                url,
                data={"agent_id": windows_agent.id, "scenario": "basic"},
                content_type="application/json",
            )

            mock_logger.info.assert_not_called()
