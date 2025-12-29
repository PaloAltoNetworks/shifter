"""Tests for engine.services.orchestration module."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.services.orchestration import (
    OrchestrationError,
    cancel,
    destroy,
    launch,
)
from mission_control.models import ActivityLog, AgentConfig, OperatingSystem, Range

User = get_user_model()


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def other_user(db):
    """Create another test user."""
    return User.objects.create_user(username="other@example.com", email="other@example.com")


@pytest.fixture
def windows_os(db):
    """Get the Windows operating system."""
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def linux_os(db):
    """Get the Linux (Debian/Ubuntu) operating system."""
    return OperatingSystem.objects.get(slug="linux-debian")


@pytest.fixture
def windows_agent(db, user, windows_os):
    """Create a Windows agent for the test user."""
    return AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test Windows Agent",
        s3_key="agents/1/test.msi",
        original_filename="test.msi",
        file_size_bytes=1024,
        sha256_hash="abc123",
    )


@pytest.fixture
def linux_agent(db, user, linux_os):
    """Create a Linux agent for the test user."""
    return AgentConfig.objects.create(
        user=user,
        os=linux_os,
        name="Test Linux Agent",
        s3_key="agents/1/test.sh",
        original_filename="test.sh",
        file_size_bytes=1024,
        sha256_hash="def456",
    )


def create_range(user, agent, status, **kwargs):
    """Helper to create a range with specific status."""
    return Range.objects.create(
        user=user,
        agent=agent,
        status=status,
        subnet_index=kwargs.get("subnet_index", 1),
        instance_config=kwargs.get("instance_config", [{"role": "attacker", "os_type": "kali"}]),
        **{k: v for k, v in kwargs.items() if k not in ("subnet_index", "instance_config")},
    )


# -----------------------------------------------------------------------------
# Tests for launch()
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestLaunch:
    """Tests for launch function."""

    @patch("engine.services.orchestration.start_provisioning")
    def test_creates_range_with_provisioning_status(self, mock_provisioning, user, windows_agent):
        """Launch should create a range with PROVISIONING status."""
        mock_provisioning.return_value = None

        range_obj = launch(user, windows_agent.id, "basic")

        assert range_obj.status == Range.Status.PROVISIONING
        assert range_obj.user == user
        assert range_obj.agent == windows_agent

    @patch("engine.services.orchestration.start_provisioning")
    def test_sets_instance_config_from_scenario(self, mock_provisioning, user, linux_agent):
        """Launch should set instance_config based on scenario and agent OS."""
        mock_provisioning.return_value = None

        range_obj = launch(user, linux_agent.id, "basic")

        # Basic scenario with Linux agent should have kali + ubuntu
        assert len(range_obj.instance_config) == 2
        assert range_obj.instance_config[0]["role"] == "attacker"
        assert range_obj.instance_config[0]["os_type"] == "kali"
        assert range_obj.instance_config[1]["role"] == "victim"
        assert range_obj.instance_config[1]["os_type"] == "ubuntu"

    @patch("engine.services.orchestration.start_provisioning")
    def test_allocates_subnet_index(self, mock_provisioning, user, windows_agent):
        """Launch should allocate a subnet index for the range."""
        mock_provisioning.return_value = None

        range_obj = launch(user, windows_agent.id, "basic")

        assert range_obj.subnet_index is not None
        assert 1 <= range_obj.subnet_index <= 254

    @patch("engine.services.orchestration.start_provisioning")
    def test_triggers_provisioner(self, mock_provisioning, user, windows_agent):
        """Launch should call start_provisioning with the range ID."""
        mock_provisioning.return_value = "arn:aws:ecs:task/12345"

        range_obj = launch(user, windows_agent.id, "basic")

        mock_provisioning.assert_called_once_with(range_obj.id)

    @patch("engine.services.orchestration.start_provisioning")
    def test_stores_task_arn_when_returned(self, mock_provisioning, user, windows_agent):
        """Launch should store the task ARN when provisioner returns one."""
        task_arn = "arn:aws:ecs:task/12345"
        mock_provisioning.return_value = task_arn

        range_obj = launch(user, windows_agent.id, "basic")

        # Refresh to get saved value
        range_obj.refresh_from_db()
        assert range_obj.step_function_execution_arn == task_arn

    @patch("engine.services.orchestration.start_provisioning")
    def test_handles_none_task_arn(self, mock_provisioning, user, windows_agent):
        """Launch should handle None task ARN (local dev without ECS)."""
        mock_provisioning.return_value = None

        range_obj = launch(user, windows_agent.id, "basic")

        range_obj.refresh_from_db()
        # step_function_execution_arn defaults to empty string, not None
        assert range_obj.step_function_execution_arn in (None, "")

    @patch("engine.services.orchestration.start_provisioning")
    def test_logs_activity(self, mock_provisioning, user, windows_agent):
        """Launch should create an activity log entry."""
        mock_provisioning.return_value = None

        range_obj = launch(user, windows_agent.id, "basic")

        log_entry = ActivityLog.objects.filter(
            user=user,
            action="range_launched",
        ).first()
        assert log_entry is not None
        assert log_entry.metadata["range_id"] == range_obj.id
        assert log_entry.metadata["agent_id"] == windows_agent.id

    @patch("engine.services.orchestration.start_provisioning")
    def test_rejects_when_active_range_exists(self, mock_provisioning, user, windows_agent):
        """Launch should raise OrchestrationError if user has active range."""
        # Create an existing active range
        create_range(user, windows_agent, Range.Status.READY, subnet_index=1)

        with pytest.raises(OrchestrationError) as exc_info:
            launch(user, windows_agent.id, "basic")

        assert "already have an active range" in str(exc_info.value).lower()
        assert exc_info.value.status_code == 409
        mock_provisioning.assert_not_called()

    @patch("engine.services.orchestration.start_provisioning")
    def test_rejects_provisioning_range_as_active(self, mock_provisioning, user, windows_agent):
        """Launch should reject when user has a range in PROVISIONING status."""
        create_range(user, windows_agent, Range.Status.PROVISIONING, subnet_index=1)

        with pytest.raises(OrchestrationError) as exc_info:
            launch(user, windows_agent.id, "basic")

        assert exc_info.value.status_code == 409
        mock_provisioning.assert_not_called()

    @patch("engine.services.orchestration.start_provisioning")
    def test_allows_launch_when_previous_range_destroyed(self, mock_provisioning, user, windows_agent):
        """Launch should succeed when previous range is DESTROYED."""
        create_range(user, windows_agent, Range.Status.DESTROYED, subnet_index=1)
        mock_provisioning.return_value = None

        range_obj = launch(user, windows_agent.id, "basic")

        assert range_obj.status == Range.Status.PROVISIONING
        # Should get a different range ID
        assert Range.objects.filter(user=user, status=Range.Status.PROVISIONING).count() == 1

    @patch("engine.services.orchestration.start_provisioning")
    def test_ad_scenario_sets_dc_agent(self, mock_provisioning, user, windows_agent):
        """AD Attack Lab scenario should set dc_agent to same as agent."""
        mock_provisioning.return_value = None

        range_obj = launch(user, windows_agent.id, "ad_attack_lab")

        assert range_obj.dc_agent == windows_agent
        assert len(range_obj.instance_config) == 3  # kali + DC + victim

    @patch("engine.services.orchestration.start_provisioning")
    def test_basic_scenario_has_no_dc_agent(self, mock_provisioning, user, windows_agent):
        """Basic scenario should not set dc_agent."""
        mock_provisioning.return_value = None

        range_obj = launch(user, windows_agent.id, "basic")

        assert range_obj.dc_agent is None

    @patch("engine.services.orchestration.start_provisioning")
    def test_returns_range_object(self, mock_provisioning, user, windows_agent):
        """Launch should return the created Range object."""
        mock_provisioning.return_value = None

        result = launch(user, windows_agent.id, "basic")

        assert isinstance(result, Range)
        assert result.pk is not None


# -----------------------------------------------------------------------------
# Tests for cancel()
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestCancel:
    """Tests for cancel function."""

    def test_sets_destroyed_status(self, user, windows_agent):
        """Cancel should set range status to DESTROYED."""
        range_obj = create_range(user, windows_agent, Range.Status.PROVISIONING)

        cancel(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYED

    def test_sets_destroyed_at_timestamp(self, user, windows_agent):
        """Cancel should set destroyed_at timestamp."""
        range_obj = create_range(user, windows_agent, Range.Status.PROVISIONING)
        assert range_obj.destroyed_at is None

        cancel(user)

        range_obj.refresh_from_db()
        assert range_obj.destroyed_at is not None

    def test_cancels_pending_range(self, user, windows_agent):
        """Cancel should work for PENDING status."""
        range_obj = create_range(user, windows_agent, Range.Status.PENDING)

        cancel(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYED

    def test_cancels_provisioning_range(self, user, windows_agent):
        """Cancel should work for PROVISIONING status."""
        range_obj = create_range(user, windows_agent, Range.Status.PROVISIONING)

        cancel(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYED

    def test_rejects_ready_range(self, user, windows_agent):
        """Cancel should reject ranges in READY status."""
        create_range(user, windows_agent, Range.Status.READY)

        with pytest.raises(OrchestrationError) as exc_info:
            cancel(user)

        assert "cannot cancel" in str(exc_info.value).lower()
        assert exc_info.value.status_code == 400

    def test_rejects_paused_range(self, user, windows_agent):
        """Cancel should reject ranges in PAUSED status."""
        create_range(user, windows_agent, Range.Status.PAUSED)

        with pytest.raises(OrchestrationError) as exc_info:
            cancel(user)

        assert "cannot cancel" in str(exc_info.value).lower()

    def test_rejects_destroying_range(self, user, windows_agent):
        """Cancel should reject ranges in DESTROYING status.

        DESTROYING ranges are not considered "active" (user can launch new range),
        so cancel returns 404 rather than 400.
        """
        create_range(user, windows_agent, Range.Status.DESTROYING)

        with pytest.raises(OrchestrationError) as exc_info:
            cancel(user)

        # DESTROYING is not "active" so returns 404
        assert exc_info.value.status_code == 404

    def test_raises_when_no_active_range(self, user):
        """Cancel should raise error when user has no active range."""
        with pytest.raises(OrchestrationError) as exc_info:
            cancel(user)

        assert "no active range" in str(exc_info.value).lower()
        assert exc_info.value.status_code == 404

    def test_logs_activity(self, user, windows_agent):
        """Cancel should create an activity log entry."""
        range_obj = create_range(user, windows_agent, Range.Status.PROVISIONING)

        cancel(user)

        log_entry = ActivityLog.objects.filter(
            user=user,
            action="range_cancelled",
        ).first()
        assert log_entry is not None
        assert log_entry.metadata["range_id"] == range_obj.id

    def test_only_cancels_own_range(self, user, other_user, windows_agent):
        """Cancel should only affect the specified user's range."""
        own_range = create_range(user, windows_agent, Range.Status.PROVISIONING, subnet_index=1)
        other_range = create_range(other_user, windows_agent, Range.Status.PROVISIONING, subnet_index=2)

        cancel(user)

        own_range.refresh_from_db()
        other_range.refresh_from_db()
        assert own_range.status == Range.Status.DESTROYED
        assert other_range.status == Range.Status.PROVISIONING  # Unchanged


# -----------------------------------------------------------------------------
# Tests for destroy()
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestDestroy:
    """Tests for destroy function."""

    @patch("engine.services.orchestration.start_teardown")
    def test_sets_destroying_status(self, mock_teardown, user, windows_agent):
        """Destroy should set range status to DESTROYING."""
        mock_teardown.return_value = None
        range_obj = create_range(user, windows_agent, Range.Status.READY)

        destroy(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    @patch("engine.services.orchestration.start_teardown")
    def test_triggers_teardown(self, mock_teardown, user, windows_agent):
        """Destroy should call start_teardown with the range ID."""
        mock_teardown.return_value = "arn:aws:ecs:task/teardown-12345"
        range_obj = create_range(user, windows_agent, Range.Status.READY)

        destroy(user)

        mock_teardown.assert_called_once_with(range_obj.id)

    @patch("engine.services.orchestration.start_teardown")
    def test_stores_task_arn_when_returned(self, mock_teardown, user, windows_agent):
        """Destroy should store the task ARN when teardown returns one."""
        task_arn = "arn:aws:ecs:task/teardown-12345"
        mock_teardown.return_value = task_arn
        range_obj = create_range(user, windows_agent, Range.Status.READY)

        destroy(user)

        range_obj.refresh_from_db()
        assert range_obj.step_function_execution_arn == task_arn

    @patch("engine.services.orchestration.start_teardown")
    def test_works_for_ready_range(self, mock_teardown, user, windows_agent):
        """Destroy should work for READY status."""
        mock_teardown.return_value = None
        range_obj = create_range(user, windows_agent, Range.Status.READY)

        destroy(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    @patch("engine.services.orchestration.start_teardown")
    def test_works_for_paused_range(self, mock_teardown, user, windows_agent):
        """Destroy should work for PAUSED status."""
        mock_teardown.return_value = None
        range_obj = create_range(user, windows_agent, Range.Status.PAUSED)

        destroy(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    @patch("engine.services.orchestration.start_teardown")
    def test_works_for_failed_range(self, mock_teardown, user, windows_agent):
        """Destroy should work for FAILED status (cleanup resources)."""
        mock_teardown.return_value = None
        range_obj = create_range(user, windows_agent, Range.Status.FAILED)

        destroy(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    @patch("engine.services.orchestration.start_teardown")
    def test_works_for_resuming_range(self, mock_teardown, user, windows_agent):
        """Destroy should work for RESUMING status."""
        mock_teardown.return_value = None
        range_obj = create_range(user, windows_agent, Range.Status.RESUMING)

        destroy(user)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_raises_when_no_destroyable_range(self, user):
        """Destroy should raise error when user has no destroyable range."""
        with pytest.raises(OrchestrationError) as exc_info:
            destroy(user)

        assert "no range to destroy" in str(exc_info.value).lower()
        assert exc_info.value.status_code == 404

    @patch("engine.services.orchestration.start_teardown")
    def test_raises_for_already_destroying_range(self, mock_teardown, user, windows_agent):
        """Destroy should raise error for range already being destroyed."""
        create_range(user, windows_agent, Range.Status.DESTROYING)

        with pytest.raises(OrchestrationError) as exc_info:
            destroy(user)

        assert exc_info.value.status_code == 404
        mock_teardown.assert_not_called()

    @patch("engine.services.orchestration.start_teardown")
    def test_logs_activity(self, mock_teardown, user, windows_agent):
        """Destroy should create an activity log entry."""
        mock_teardown.return_value = None
        range_obj = create_range(user, windows_agent, Range.Status.READY)

        destroy(user)

        log_entry = ActivityLog.objects.filter(
            user=user,
            action="range_destroyed",
        ).first()
        assert log_entry is not None
        assert log_entry.metadata["range_id"] == range_obj.id

    @patch("engine.services.orchestration.start_teardown")
    def test_only_destroys_own_range(self, mock_teardown, user, other_user, windows_agent):
        """Destroy should only affect the specified user's range."""
        mock_teardown.return_value = None
        own_range = create_range(user, windows_agent, Range.Status.READY, subnet_index=1)
        other_range = create_range(other_user, windows_agent, Range.Status.READY, subnet_index=2)

        destroy(user)

        own_range.refresh_from_db()
        other_range.refresh_from_db()
        assert own_range.status == Range.Status.DESTROYING
        assert other_range.status == Range.Status.READY  # Unchanged


# -----------------------------------------------------------------------------
# Tests for OrchestrationError
# -----------------------------------------------------------------------------


class TestOrchestrationError:
    """Tests for the OrchestrationError exception class."""

    def test_default_status_code_is_400(self):
        """Default status code should be 400 (Bad Request)."""
        error = OrchestrationError("Test error")
        assert error.status_code == 400

    def test_custom_status_code(self):
        """Should accept custom status code."""
        error = OrchestrationError("Not found", status_code=404)
        assert error.status_code == 404

    def test_conflict_status_code(self):
        """Should support 409 Conflict status code."""
        error = OrchestrationError("Already exists", status_code=409)
        assert error.status_code == 409

    def test_message_accessible_via_str(self):
        """Error message should be accessible via str()."""
        error = OrchestrationError("Custom message")
        assert str(error) == "Custom message"

    def test_is_exception(self):
        """OrchestrationError should be an Exception."""
        error = OrchestrationError("Test")
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Should be raisable and catchable."""
        with pytest.raises(OrchestrationError):
            raise OrchestrationError("Test")
