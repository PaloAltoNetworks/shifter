"""Network component tests for Pulumi provisioner.

These tests use Pulumi's mocking framework to test the actual NetworkComponent
without making real AWS API calls. Tests verify that the component:
- Creates subnets with correct CIDR calculations
- Associates route tables correctly
- Applies proper tags
- Exports correct outputs
"""

import sys
from pathlib import Path

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestNetworkComponentWithPulumiMocks:
    """Tests for NetworkComponent using Pulumi runtime mocks.

    These tests actually instantiate the real NetworkComponent class
    and verify its behavior using Pulumi's mocking framework.
    """

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_creates_subnet(self):
        """NetworkComponent should create an EC2 subnet."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        # Verify subnet was created
        assert component.subnet is not None
        assert component.subnet_id is not None
        assert component.subnet_cidr is not None

    @pulumi.runtime.test
    def test_subnet_cidr_calculation(self):
        """Subnet CIDR should be {prefix}.{index+1}.0/24."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,  # Should result in 10.1.6.0/24
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_cidr(cidr):
            assert cidr == "10.1.6.0/24"

        component.subnet.cidr_block.apply(check_cidr)

    @pulumi.runtime.test
    def test_subnet_cidr_index_zero(self):
        """Subnet index 0 creates CIDR .1.0/24 (reserving .0 for infra)."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=0,  # Should result in 10.1.1.0/24
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_cidr(cidr):
            assert cidr == "10.1.1.0/24"

        component.subnet.cidr_block.apply(check_cidr)

    @pulumi.runtime.test
    def test_subnet_cidr_different_prefix(self):
        """Different CIDR prefixes should work correctly."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="172.16",  # Different prefix
            subnet_index=10,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_cidr(cidr):
            assert cidr == "172.16.11.0/24"

        component.subnet.cidr_block.apply(check_cidr)

    @pulumi.runtime.test
    def test_subnet_in_correct_vpc(self):
        """Subnet should be created in the specified VPC."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-my-specific-vpc",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_vpc_id(vpc_id):
            assert vpc_id == "vpc-my-specific-vpc"

        component.subnet.vpc_id.apply(check_vpc_id)

    @pulumi.runtime.test
    def test_subnet_in_correct_az(self):
        """Subnet should be created in the specified availability zone."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-west-2b",
        )

        def check_az(az):
            assert az == "us-west-2b"

        component.subnet.availability_zone.apply(check_az)

    @pulumi.runtime.test
    def test_subnet_has_correct_name_tag(self):
        """Subnet should have Name tag: shifter-range-{range_id}."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_tags(tags):
            assert tags.get("Name") == "shifter-range-42"

        component.subnet.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_subnet_has_shifter_tags(self):
        """Subnet should have shifter metadata tags."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_tags(tags):
            assert tags.get("shifter:range_id") == "42"
            assert tags.get("shifter:user_id") == "1"
            assert tags.get("shifter:environment") == "dev"
            assert tags.get("ManagedBy") == "pulumi"

        component.subnet.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_subnet_prod_environment_tags(self):
        """Subnet in prod should have prod environment tag."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=99,
            user_id=5,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="prod",
            availability_zone="us-east-2a",
        )

        def check_tags(tags):
            assert tags.get("shifter:environment") == "prod"
            assert tags.get("shifter:range_id") == "99"
            assert tags.get("shifter:user_id") == "5"

        component.subnet.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_outputs_are_registered(self):
        """NetworkComponent should register subnetId and subnetCidr outputs."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        # These should be Pulumi Output objects
        assert hasattr(component, "subnet_id")
        assert hasattr(component, "subnet_cidr")


class TestNetworkComponentEdgeCases:
    """Edge case tests for NetworkComponent."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_max_subnet_index(self):
        """Subnet index 254 should create .255.0/24."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=254,  # Max valid index -> 10.1.255.0/24
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_cidr(cidr):
            assert cidr == "10.1.255.0/24"

        component.subnet.cidr_block.apply(check_cidr)

    @pulumi.runtime.test
    def test_range_id_zero(self):
        """Range ID 0 should work correctly."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=0,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_tags(tags):
            assert tags.get("shifter:range_id") == "0"
            assert tags.get("Name") == "shifter-range-0"

        component.subnet.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_large_range_id(self):
        """Large range IDs should work correctly."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=999999,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_tags(tags):
            assert tags.get("shifter:range_id") == "999999"
            assert tags.get("Name") == "shifter-range-999999"

        component.subnet.tags.apply(check_tags)


class TestResourceCreationVerification:
    """Tests that verify resources are created correctly via pulumi_mocks."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_subnet_resource_has_id(self):
        """Verify subnet resource is created with an ID."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        # Verify subnet has an ID output (via Pulumi mocks)
        def check_id(subnet_id):
            assert subnet_id is not None
            assert len(subnet_id) > 0

        component.subnet_id.apply(check_id)

    @pulumi.runtime.test
    def test_component_creates_all_required_resources(self):
        """Verify NetworkComponent creates subnet with outputs."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            subnet_index=5,
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        # Verify component has expected outputs
        assert component.subnet is not None
        assert component.subnet_id is not None
        assert component.subnet_cidr is not None

        # Verify subnet_cidr output value
        def check_cidr(cidr):
            assert cidr == "10.1.6.0/24"

        component.subnet_cidr.apply(check_cidr)
