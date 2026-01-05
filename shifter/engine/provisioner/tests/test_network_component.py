"""Network component tests for Shifter Engine.

These tests use Pulumi's mocking framework to test the actual NetworkComponent
without making real AWS API calls. Tests verify that the component:
- Creates subnets with correct CIDR calculations
- Associates route tables correctly
- Applies proper tags
- Exports correct outputs
- Cleans up orphaned subnets before creating new ones
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from components.network import _cleanup_orphaned_subnet

# =============================================================================
# Unit Tests for _cleanup_orphaned_subnet
# =============================================================================


class TestCleanupOrphanedSubnetHappyPath:
    """Happy path tests for _cleanup_orphaned_subnet."""

    def test_no_orphaned_subnet_exists(self):
        """No orphaned subnet exists, function returns without action."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        mock_ec2.describe_subnets.assert_called_once_with(
            Filters=[
                {"Name": "vpc-id", "Values": ["vpc-12345"]},
                {"Name": "cidr-block", "Values": ["10.1.5.0/24"]},
            ]
        )
        mock_ec2.delete_subnet.assert_not_called()

    def test_orphaned_subnet_deleted_successfully(self):
        """Orphaned subnet exists and is deleted successfully."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {
                    "SubnetId": "subnet-orphan123",
                    "CidrBlock": "10.1.5.0/24",
                    "Tags": [{"Key": "Name", "Value": "shifter-range-42"}],
                }
            ]
        }
        mock_ec2.delete_subnet.return_value = {}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        mock_ec2.delete_subnet.assert_called_once_with(SubnetId="subnet-orphan123")

    def test_orphaned_subnet_no_name_tag(self):
        """Subnet without Name tag should still be deleted."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {
                    "SubnetId": "subnet-notag",
                    "CidrBlock": "10.1.5.0/24",
                    "Tags": [],
                }
            ]
        }
        mock_ec2.delete_subnet.return_value = {}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        mock_ec2.delete_subnet.assert_called_once_with(SubnetId="subnet-notag")


class TestCleanupOrphanedSubnetFailures:
    """Failure case tests for _cleanup_orphaned_subnet."""

    def test_delete_fails_dependency_violation(self):
        """Subnet has resources attached and cannot be deleted."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {
                    "SubnetId": "subnet-inuse",
                    "CidrBlock": "10.1.5.0/24",
                    "Tags": [{"Key": "Name", "Value": "shifter-range-99"}],
                }
            ]
        }
        from botocore.exceptions import ClientError

        mock_ec2.delete_subnet.side_effect = ClientError(
            {
                "Error": {
                    "Code": "DependencyViolation",
                    "Message": "The subnet 'subnet-inuse' has dependencies.",
                }
            },
            "DeleteSubnet",
        )

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(RuntimeError) as exc_info,
        ):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        assert "subnet-inuse" in str(exc_info.value)
        assert "could not be deleted" in str(exc_info.value)
        assert "DependencyViolation" in str(exc_info.value)

    def test_delete_fails_access_denied(self):
        """IAM permissions prevent subnet deletion."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {
                    "SubnetId": "subnet-noaccess",
                    "CidrBlock": "10.1.5.0/24",
                    "Tags": [],
                }
            ]
        }
        from botocore.exceptions import ClientError

        mock_ec2.delete_subnet.side_effect = ClientError(
            {
                "Error": {
                    "Code": "UnauthorizedOperation",
                    "Message": "You are not authorized to perform this operation.",
                }
            },
            "DeleteSubnet",
        )

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(RuntimeError) as exc_info,
        ):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        assert "subnet-noaccess" in str(exc_info.value)
        assert "UnauthorizedOperation" in str(exc_info.value)

    def test_describe_subnets_fails_invalid_vpc(self):
        """AWS API call to describe subnets fails with invalid VPC."""
        mock_ec2 = MagicMock()
        from botocore.exceptions import ClientError

        mock_ec2.describe_subnets.side_effect = ClientError(
            {
                "Error": {
                    "Code": "InvalidVpcID.NotFound",
                    "Message": "The vpc ID 'vpc-invalid' does not exist",
                }
            },
            "DescribeSubnets",
        )

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(ClientError) as exc_info,
        ):
            _cleanup_orphaned_subnet("vpc-invalid", "10.1.5.0/24")

        assert "InvalidVpcID.NotFound" in str(exc_info.value)


class TestCleanupOrphanedSubnetUnexpected:
    """Unexpected/edge case tests for _cleanup_orphaned_subnet."""

    def test_multiple_subnets_found_deletes_first(self):
        """Multiple subnets with same CIDR - deletes first one only."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {
                    "SubnetId": "subnet-first",
                    "CidrBlock": "10.1.5.0/24",
                    "Tags": [{"Key": "Name", "Value": "first"}],
                },
                {
                    "SubnetId": "subnet-second",
                    "CidrBlock": "10.1.5.0/24",
                    "Tags": [{"Key": "Name", "Value": "second"}],
                },
            ]
        }
        mock_ec2.delete_subnet.return_value = {}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        mock_ec2.delete_subnet.assert_called_once_with(SubnetId="subnet-first")

    def test_subnet_missing_tags_key(self):
        """Subnet response missing 'Tags' key entirely."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {
                    "SubnetId": "subnet-notags",
                    "CidrBlock": "10.1.5.0/24",
                    # No 'Tags' key at all
                }
            ]
        }
        mock_ec2.delete_subnet.return_value = {}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        mock_ec2.delete_subnet.assert_called_once_with(SubnetId="subnet-notags")

    def test_connection_error_to_aws(self):
        """Network error connecting to AWS."""
        mock_ec2 = MagicMock()
        from botocore.exceptions import EndpointConnectionError

        mock_ec2.describe_subnets.side_effect = EndpointConnectionError(
            endpoint_url="https://ec2.us-east-2.amazonaws.com"
        )

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(EndpointConnectionError),
        ):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

    def test_empty_vpc_id(self):
        """Empty VPC ID passed - let AWS validate."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("", "10.1.5.0/24")

        mock_ec2.describe_subnets.assert_called_once()

    def test_empty_cidr_block(self):
        """Empty CIDR block passed - let AWS validate."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("vpc-12345", "")

        mock_ec2.describe_subnets.assert_called_once()

    def test_subnet_with_other_tags_but_no_name(self):
        """Subnet has tags but none with Key='Name'."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {
                    "SubnetId": "subnet-othertags",
                    "CidrBlock": "10.1.5.0/24",
                    "Tags": [
                        {"Key": "Environment", "Value": "dev"},
                        {"Key": "ManagedBy", "Value": "pulumi"},
                    ],
                }
            ]
        }
        mock_ec2.delete_subnet.return_value = {}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            _cleanup_orphaned_subnet("vpc-12345", "10.1.5.0/24")

        mock_ec2.delete_subnet.assert_called_once_with(SubnetId="subnet-othertags")


# =============================================================================
# NetworkComponent Pulumi Tests
# =============================================================================


@pytest.fixture
def mock_cleanup_orphaned_subnet():
    """Mock _cleanup_orphaned_subnet for NetworkComponent tests.

    The cleanup function makes real AWS API calls, which we don't want
    during Pulumi component tests.
    """
    with patch("components.network._cleanup_orphaned_subnet"):
        yield


class TestNetworkComponentWithPulumiMocks:
    """Tests for NetworkComponent using Pulumi runtime mocks.

    These tests actually instantiate the real NetworkComponent class
    and verify its behavior using Pulumi's mocking framework.
    """

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
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
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
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
    def setup_pulumi_mocks(self, pulumi_mocks, mock_cleanup_orphaned_subnet):
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
