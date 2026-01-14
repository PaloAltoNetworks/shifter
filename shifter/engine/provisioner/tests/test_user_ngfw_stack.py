"""Tests for UserNGFWStack.

UserNGFWStack composes NGFWComponent + GWLBComponent for persistent
per-user NGFW lifecycle management.
"""

from unittest.mock import MagicMock

import pulumi
import pytest


@pytest.fixture(autouse=True)
def setup_pulumi_mocks():
    """Set up Pulumi mocks for testing."""
    pulumi.runtime.set_mocks(
        MagicMock(
            call=lambda args: {},
            new_resource=lambda args: [f"{args.name}-id", args.inputs],
        ),
        preview=False,
    )
    yield


@pytest.fixture
def stack():
    """Create a UserNGFWStack instance for testing."""
    from stacks.user_ngfw_stack import UserNGFWStack

    return UserNGFWStack(
        "test-stack",
        user_id=123,
        vpc_id="vpc-12345",
        ngfw_subnet_id="subnet-ngfw",
        ngfw_mgmt_security_group_id="sg-mgmt",
        ngfw_data_security_group_id="sg-data",
        ami_id="ami-12345",
        bootstrap_bucket="test-bucket",
        scm_pin_id="pin-123",
        scm_pin_value="pin-value-456",
        scm_folder_name="test-folder",
        authcode="I1234567",
        request_uuid="req-uuid-12345",
        instance_uuid="inst-uuid-12345",
    )


class TestUserNGFWStackComposition:
    """Test UserNGFWStack component composition."""

    def test_stack_can_be_instantiated(self, stack):
        """UserNGFWStack should be instantiatable with required params."""
        assert stack is not None


class TestUserNGFWStackRunProvision:
    """Test UserNGFWStack.run_provision method."""

    def test_run_provision_returns_result(self, stack):
        """run_provision should call orchestrator and return result."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_provision(mock_orchestrator)
        assert result is not None


class TestUserNGFWStackRunDeprovision:
    """Test UserNGFWStack.run_deprovision method."""

    def test_run_deprovision_returns_result(self, stack):
        """run_deprovision should call orchestrator and return result."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_deprovision(mock_orchestrator)
        assert result is not None


class TestUserNGFWStackRunOps:
    """Test UserNGFWStack.run_ops method."""

    def test_run_ops_start_returns_result(self, stack):
        """run_ops with 'start' operation should return a result."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_ops("start", orchestrator=mock_orchestrator)
        assert result is not None

    def test_run_ops_stop_returns_result(self, stack):
        """run_ops with 'stop' operation should return a result."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_ops("stop", orchestrator=mock_orchestrator)
        assert result is not None

    def test_run_ops_invalid_operation_raises(self, stack):
        """run_ops with invalid operation should raise ValueError."""
        mock_orchestrator = MagicMock()

        with pytest.raises(ValueError, match="Unknown operation"):
            stack.run_ops("invalid_op", orchestrator=mock_orchestrator)
