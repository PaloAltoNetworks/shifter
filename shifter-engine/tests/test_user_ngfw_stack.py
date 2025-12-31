"""Tests for UserNGFWStack - TDD: Write tests first, all must fail initially.

UserNGFWStack composes NGFWComponent + GWLBComponent for persistent
per-user NGFW lifecycle management.
"""

from unittest.mock import MagicMock, patch

import pytest
import pulumi


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
        from stacks.user_ngfw_stack import UserNGFWStack
        import inspect

        sig = inspect.signature(UserNGFWStack.__init__)
        params = list(sig.parameters.keys())

        # Should have user_id, vpc_id, subnet, security group, ami
        assert "user_id" in params
        assert "vpc_id" in params
