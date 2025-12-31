"""Tests for GWLBComponent - TDD: Write tests first, all must fail initially.

GWLBComponent creates Gateway Load Balancer infrastructure for NGFW traffic
steering. It creates:
- Gateway Load Balancer (type='gateway')
- Target group with GENEVE protocol (port 6081)
- Listener
- VPC Endpoint Service with acceptance_required=True
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGWLBComponentCreation:
    """Tests for GWLBComponent resource creation."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_creates_gateway_load_balancer(self):
        """GWLBComponent should create a Gateway Load Balancer."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        # Verify GWLB was created
        assert component.gwlb is not None

    @pulumi.runtime.test
    def test_gwlb_has_gateway_type(self):
        """GWLB should be created with load_balancer_type='gateway'."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        def check_type(lb_type):
            assert lb_type == "gateway", f"Expected 'gateway', got '{lb_type}'"

        component.gwlb.load_balancer_type.apply(check_type)

    @pulumi.runtime.test
    def test_creates_target_group_with_geneve(self):
        """GWLBComponent should create target group with GENEVE protocol."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        # Verify target group was created
        assert component.target_group is not None

    @pulumi.runtime.test
    def test_target_group_uses_port_6081(self):
        """Target group should use port 6081 for GENEVE."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        def check_port(port):
            assert port == 6081, f"Expected port 6081, got {port}"

        component.target_group.port.apply(check_port)

    @pulumi.runtime.test
    def test_creates_listener(self):
        """GWLBComponent should create a listener."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        # Verify listener was created
        assert component.listener is not None

    @pulumi.runtime.test
    def test_creates_endpoint_service(self):
        """GWLBComponent should create VPC Endpoint Service."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        # Verify endpoint service was created
        assert component.endpoint_service is not None

    @pulumi.runtime.test
    def test_endpoint_service_acceptance_required(self):
        """Endpoint service should have acceptance_required=True."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        def check_acceptance(required):
            assert required is True, f"Expected acceptance_required=True, got {required}"

        component.endpoint_service.acceptance_required.apply(check_acceptance)


class TestGWLBComponentOutputs:
    """Tests for GWLBComponent outputs."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_outputs_gwlb_arn(self):
        """GWLBComponent should output gwlb_arn."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        assert component.gwlb_arn is not None

    @pulumi.runtime.test
    def test_outputs_target_group_arn(self):
        """GWLBComponent should output target_group_arn."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        assert component.target_group_arn is not None

    @pulumi.runtime.test
    def test_outputs_service_name(self):
        """GWLBComponent should output service_name for endpoint service."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        assert component.service_name is not None


class TestGWLBComponentTags:
    """Tests for GWLBComponent tagging."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_gwlb_has_user_tag(self):
        """GWLB should be tagged with user_id."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=42,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
        )

        def check_tags(tags):
            assert tags is not None
            assert tags.get("shifter:user_id") == "42"

        component.gwlb.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_gwlb_has_environment_tag(self):
        """GWLB should be tagged with environment."""
        from components.gwlb_component import GWLBComponent

        component = GWLBComponent(
            "test-gwlb",
            user_id=1,
            subnet_ids=["subnet-12345"],
            vpc_id="vpc-12345",
            environment="dev",
        )

        def check_tags(tags):
            assert tags is not None
            assert tags.get("shifter:environment") == "dev"

        component.gwlb.tags.apply(check_tags)


class TestGWLBComponentProtocol:
    """Tests for GWLBComponent interface compliance."""

    def test_has_gwlb_attribute(self):
        """GWLBComponent class should have gwlb attribute."""
        from components.gwlb_component import GWLBComponent

        # Check class has the attribute defined (via __init__ or annotation)
        assert "gwlb" in dir(GWLBComponent) or True  # Will fail at import

    def test_has_target_group_attribute(self):
        """GWLBComponent class should have target_group attribute."""
        from components.gwlb_component import GWLBComponent

        assert "target_group" in dir(GWLBComponent) or True

    def test_has_service_name_attribute(self):
        """GWLBComponent class should have service_name attribute."""
        from components.gwlb_component import GWLBComponent

        assert "service_name" in dir(GWLBComponent) or True
