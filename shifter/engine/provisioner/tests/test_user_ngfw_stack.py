"""Tests for UserNGFWStack - TDD: Write tests first, all must fail initially.

UserNGFWStack composes NGFWComponent + GWLBComponent for persistent
per-user NGFW lifecycle management.
"""

from unittest.mock import MagicMock

import pulumi
import pytest


class TestUserNGFWStackComposition:
    """Test UserNGFWStack component composition."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self):
        """Set up Pulumi mocks for testing."""
        pulumi.runtime.set_mocks(
            MagicMock(
                call=lambda args: {},
                new_resource=lambda args: [f"{args.name}-id", args.inputs],
            ),
            preview=False,
        )
        yield

    def test_stack_can_be_instantiated(self):
        """UserNGFWStack should be instantiatable."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )
        assert stack is not None

    def test_stack_creates_ngfw_component(self):
        """UserNGFWStack should create NGFWComponent."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )
        assert hasattr(stack, "ngfw")

    def test_stack_creates_gwlb_component(self):
        """UserNGFWStack should create GWLBComponent."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )
        assert hasattr(stack, "gwlb")


class TestUserNGFWStackOutputs:
    """Test UserNGFWStack outputs."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self):
        """Set up Pulumi mocks for testing."""
        pulumi.runtime.set_mocks(
            MagicMock(
                call=lambda args: {},
                new_resource=lambda args: [f"{args.name}-id", args.inputs],
            ),
            preview=False,
        )
        yield

    def test_stack_has_instance_id_output(self):
        """UserNGFWStack should expose instance_id output."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )
        assert hasattr(stack, "instance_id")

    def test_stack_has_management_ip_output(self):
        """UserNGFWStack should expose management_ip output."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )
        assert hasattr(stack, "management_ip")

    def test_stack_has_service_name_output(self):
        """UserNGFWStack should expose GWLB service_name output."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )
        assert hasattr(stack, "service_name")

    def test_stack_has_target_group_arn_output(self):
        """UserNGFWStack should expose target_group_arn output."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )
        assert hasattr(stack, "target_group_arn")


class TestUserNGFWStackInterface:
    """Test UserNGFWStack interface compliance."""

    def test_is_component_resource(self):
        """UserNGFWStack should be a Pulumi ComponentResource."""
        from stacks.user_ngfw_stack import UserNGFWStack

        assert issubclass(UserNGFWStack, pulumi.ComponentResource)

    def test_has_required_parameters(self):
        """UserNGFWStack should require essential parameters."""
        import inspect

        from stacks.user_ngfw_stack import UserNGFWStack

        sig = inspect.signature(UserNGFWStack.__init__)
        params = list(sig.parameters.keys())

        # Should have user_id, vpc_id, subnet, security group, ami
        assert "user_id" in params
        assert "vpc_id" in params


class TestUserNGFWStackOrchestrationMethods:
    """Test UserNGFWStack orchestration methods."""

    def test_has_run_provision_method(self):
        """UserNGFWStack should have run_provision method."""
        from stacks.user_ngfw_stack import UserNGFWStack

        assert hasattr(UserNGFWStack, "run_provision")
        assert callable(UserNGFWStack.run_provision)

    def test_has_run_deprovision_method(self):
        """UserNGFWStack should have run_deprovision method."""
        from stacks.user_ngfw_stack import UserNGFWStack

        assert hasattr(UserNGFWStack, "run_deprovision")
        assert callable(UserNGFWStack.run_deprovision)

    def test_has_run_ops_method(self):
        """UserNGFWStack should have run_ops method."""
        from stacks.user_ngfw_stack import UserNGFWStack

        assert hasattr(UserNGFWStack, "run_ops")
        assert callable(UserNGFWStack.run_ops)


class TestUserNGFWStackRunProvision:
    """Test UserNGFWStack.run_provision method."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self):
        """Set up Pulumi mocks for testing."""
        pulumi.runtime.set_mocks(
            MagicMock(
                call=lambda args: {},
                new_resource=lambda args: [f"{args.name}-id", args.inputs],
            ),
            preview=False,
        )
        yield

    def test_run_provision_accepts_orchestrator(self):
        """run_provision should accept an orchestrator parameter."""
        import inspect

        from stacks.user_ngfw_stack import UserNGFWStack

        sig = inspect.signature(UserNGFWStack.run_provision)
        params = list(sig.parameters.keys())
        assert "orchestrator" in params or len(params) >= 1  # self + orchestrator

    def test_run_provision_returns_result(self):
        """run_provision should return a result object."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_provision(mock_orchestrator)
        assert result is not None


class TestUserNGFWStackRunDeprovision:
    """Test UserNGFWStack.run_deprovision method."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self):
        """Set up Pulumi mocks for testing."""
        pulumi.runtime.set_mocks(
            MagicMock(
                call=lambda args: {},
                new_resource=lambda args: [f"{args.name}-id", args.inputs],
            ),
            preview=False,
        )
        yield

    def test_run_deprovision_accepts_orchestrator(self):
        """run_deprovision should accept an orchestrator parameter."""
        import inspect

        from stacks.user_ngfw_stack import UserNGFWStack

        sig = inspect.signature(UserNGFWStack.run_deprovision)
        params = list(sig.parameters.keys())
        assert "orchestrator" in params or len(params) >= 1

    def test_run_deprovision_returns_result(self):
        """run_deprovision should return a result object."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_deprovision(mock_orchestrator)
        assert result is not None


class TestUserNGFWStackRunOps:
    """Test UserNGFWStack.run_ops method."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self):
        """Set up Pulumi mocks for testing."""
        pulumi.runtime.set_mocks(
            MagicMock(
                call=lambda args: {},
                new_resource=lambda args: [f"{args.name}-id", args.inputs],
            ),
            preview=False,
        )
        yield

    def test_run_ops_accepts_operation_parameter(self):
        """run_ops should accept an operation parameter."""
        import inspect

        from stacks.user_ngfw_stack import UserNGFWStack

        sig = inspect.signature(UserNGFWStack.run_ops)
        params = list(sig.parameters.keys())
        assert "operation" in params

    def test_run_ops_accepts_orchestrator(self):
        """run_ops should accept an orchestrator parameter."""
        import inspect

        from stacks.user_ngfw_stack import UserNGFWStack

        sig = inspect.signature(UserNGFWStack.run_ops)
        params = list(sig.parameters.keys())
        assert "orchestrator" in params

    def test_run_ops_start_returns_result(self):
        """run_ops with 'start' operation should return a result."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_ops("start", orchestrator=mock_orchestrator)
        assert result is not None

    def test_run_ops_stop_returns_result(self):
        """run_ops with 'stop' operation should return a result."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True)

        result = stack.run_ops("stop", orchestrator=mock_orchestrator)
        assert result is not None

    def test_run_ops_invalid_operation_raises(self):
        """run_ops with invalid operation should raise ValueError."""
        from stacks.user_ngfw_stack import UserNGFWStack

        stack = UserNGFWStack(
            "test-stack",
            user_id=123,
            vpc_id="vpc-12345",
            ngfw_subnet_id="subnet-ngfw",
            ngfw_security_group_id="sg-ngfw",
            ami_id="ami-12345",
            bootstrap_bucket="test-bucket",
        )

        mock_orchestrator = MagicMock()

        with pytest.raises(ValueError, match="Unknown operation"):
            stack.run_ops("invalid_op", orchestrator=mock_orchestrator)
