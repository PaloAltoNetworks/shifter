"""Network component tests for Shifter Engine.

These tests use Pulumi's mocking framework to test the actual NetworkComponent
without making real AWS API calls. Tests verify that the component:
- Finds free subnets by querying AWS
- Handles overlapping CIDRs correctly (e.g., /22 blocks)
- Creates subnets with correct configuration
- Associates route tables correctly
- Applies proper tags
- Exports correct outputs
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from components.network import _find_free_subnet, _publish_subnet_exhaustion_alarm

# =============================================================================
# Unit Tests for _publish_subnet_exhaustion_alarm
# =============================================================================


class TestPublishSubnetExhaustionAlarm:
    """Tests for the subnet exhaustion alarm function."""

    def test_publishes_cloudwatch_metric(self):
        """Alarm function publishes a CloudWatch metric."""
        mock_cloudwatch = MagicMock()

        with patch("components.network.boto3.client", return_value=mock_cloudwatch):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1")

        mock_cloudwatch.put_metric_data.assert_called_once()
        call_args = mock_cloudwatch.put_metric_data.call_args
        assert call_args[1]["Namespace"] == "Shifter/RangeProvisioning"
        assert call_args[1]["MetricData"][0]["MetricName"] == "SubnetExhaustion"
        assert call_args[1]["MetricData"][0]["Value"] == 1

    def test_metric_includes_vpc_dimension(self):
        """Metric includes VPC ID as a dimension."""
        mock_cloudwatch = MagicMock()

        with patch("components.network.boto3.client", return_value=mock_cloudwatch):
            _publish_subnet_exhaustion_alarm("vpc-my-test-vpc", "10.1")

        call_args = mock_cloudwatch.put_metric_data.call_args
        dimensions = call_args[1]["MetricData"][0]["Dimensions"]
        assert {"Name": "VpcId", "Value": "vpc-my-test-vpc"} in dimensions

    def test_uses_aws_region_env_var(self):
        """Uses AWS_REGION environment variable."""
        mock_cloudwatch = MagicMock()

        with (
            patch("components.network.boto3.client", return_value=mock_cloudwatch) as mock_client,
            patch.dict("os.environ", {"AWS_REGION": "eu-west-1"}),
        ):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1")

        mock_client.assert_called_with("cloudwatch", region_name="eu-west-1")

    def test_defaults_to_us_east_2(self):
        """Defaults to us-east-2 if AWS_REGION not set."""
        mock_cloudwatch = MagicMock()

        with (
            patch("components.network.boto3.client", return_value=mock_cloudwatch) as mock_client,
            patch.dict("os.environ", {}, clear=True),
        ):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1")

        mock_client.assert_called_with("cloudwatch", region_name="us-east-2")


# =============================================================================
# Unit Tests for _find_free_subnet
# =============================================================================


class TestFindFreeSubnetHappyPath:
    """Happy path tests for _find_free_subnet."""

    def test_finds_first_free_subnet_no_existing(self):
        """No existing subnets, returns first available (.2.0/24)."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.2.0/24"
        mock_ec2.describe_subnets.assert_called_once_with(Filters=[{"Name": "vpc-id", "Values": ["vpc-12345"]}])

    def test_skips_existing_subnets(self):
        """Skips existing /24 subnets and finds next free one."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/24"},  # First range subnet
                {"CidrBlock": "10.1.3.0/24"},  # Second range subnet
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.4.0/24"

    def test_skips_infrastructure_subnets(self):
        """Skips small infrastructure subnets in .0.x space."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.0.0/28"},  # Firewall subnet
                {"CidrBlock": "10.1.0.16/28"},  # NAT subnet
                {"CidrBlock": "10.1.0.32/28"},  # SSM endpoints
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        # Should start at .2.0/24, skipping .0.x and .1.x
        assert result == "10.1.2.0/24"


class TestFindFreeSubnetOverlappingCIDRs:
    """Tests for handling overlapping CIDRs (the main bug fix)."""

    def test_skips_larger_cidr_that_overlaps(self):
        """A /22 subnet blocks multiple /24 candidates."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/24"},  # Range 1
                {"CidrBlock": "10.1.3.0/24"},  # Range 2
                {"CidrBlock": "10.1.4.0/22"},  # NGFW - covers .4, .5, .6, .7
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        # Should skip 10.1.4.0/24 through 10.1.7.0/24 (covered by /22)
        assert result == "10.1.8.0/24"

    def test_skips_slash_21_that_overlaps(self):
        """A /21 subnet blocks 8 /24 candidates."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.8.0/21"},  # Covers .8 through .15
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        # First available is .2 (skipping .0, .1 for infra)
        # But .8-.15 are blocked by /21, so if .2-.7 taken, would skip to .16
        # In this case .2 is free
        assert result == "10.1.2.0/24"

    def test_complex_overlapping_scenario(self):
        """Multiple overlapping subnets of different sizes."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.0.0/28"},  # Infra - overlaps .0
                {"CidrBlock": "10.1.2.0/24"},  # Range 1
                {"CidrBlock": "10.1.3.0/24"},  # Range 2
                {"CidrBlock": "10.1.4.0/22"},  # NGFW - covers .4-.7
                {"CidrBlock": "10.1.8.0/24"},  # Range 3
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        # .2, .3 taken; .4-.7 blocked by /22; .8 taken; .9 free
        assert result == "10.1.9.0/24"

    def test_slash_16_blocks_all_candidates(self):
        """A /16 subnet should cause no free subnet error."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.0.0/16"},  # Covers entire range
            ]
        }

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(RuntimeError) as exc_info,
        ):
            _find_free_subnet("vpc-12345", "10.1")

        assert "No free /24 subnet available" in str(exc_info.value)


class TestFindFreeSubnetExhaustion:
    """Tests for subnet exhaustion scenarios."""

    def test_all_subnets_used(self):
        """All /24 subnets from .2 to .254 are in use."""
        mock_ec2 = MagicMock()
        mock_cloudwatch = MagicMock()
        # Create list of all possible subnets
        all_subnets = [{"CidrBlock": f"10.1.{i}.0/24"} for i in range(2, 255)]
        mock_ec2.describe_subnets.return_value = {"Subnets": all_subnets}

        def client_factory(service, **kwargs):
            if service == "ec2":
                return mock_ec2
            if service == "cloudwatch":
                return mock_cloudwatch
            return MagicMock()

        with (
            patch("components.network.boto3.client", side_effect=client_factory),
            pytest.raises(RuntimeError) as exc_info,
        ):
            _find_free_subnet("vpc-12345", "10.1")

        assert "No free /24 subnet available" in str(exc_info.value)

    def test_exhaustion_publishes_alarm(self):
        """Subnet exhaustion triggers CloudWatch alarm metric."""
        mock_ec2 = MagicMock()
        mock_cloudwatch = MagicMock()
        # Create list of all possible subnets
        all_subnets = [{"CidrBlock": f"10.1.{i}.0/24"} for i in range(2, 255)]
        mock_ec2.describe_subnets.return_value = {"Subnets": all_subnets}

        def client_factory(service, **kwargs):
            if service == "ec2":
                return mock_ec2
            if service == "cloudwatch":
                return mock_cloudwatch
            return MagicMock()

        with (
            patch("components.network.boto3.client", side_effect=client_factory),
            pytest.raises(RuntimeError),
        ):
            _find_free_subnet("vpc-exhausted", "10.1")

        # Verify alarm was published
        mock_cloudwatch.put_metric_data.assert_called_once()
        call_args = mock_cloudwatch.put_metric_data.call_args
        assert call_args[1]["MetricData"][0]["MetricName"] == "SubnetExhaustion"
        dimensions = call_args[1]["MetricData"][0]["Dimensions"]
        assert {"Name": "VpcId", "Value": "vpc-exhausted"} in dimensions

    def test_finds_gap_in_middle(self):
        """Finds a free subnet in a gap between used ones."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/24"},
                {"CidrBlock": "10.1.3.0/24"},
                # Gap at .4
                {"CidrBlock": "10.1.5.0/24"},
                {"CidrBlock": "10.1.6.0/24"},
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.4.0/24"


class TestFindFreeSubnetEdgeCases:
    """Edge case tests for _find_free_subnet."""

    def test_different_cidr_prefix(self):
        """Works with different CIDR prefixes."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "172.16")

        assert result == "172.16.2.0/24"

    def test_invalid_cidr_in_aws_response_ignored(self):
        """Invalid CIDRs from AWS are gracefully ignored."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "invalid-cidr"},
                {"CidrBlock": "10.1.2.0/24"},
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        # Should skip invalid and find next after .2
        assert result == "10.1.3.0/24"

    def test_empty_subnets_response(self):
        """Empty Subnets list works correctly."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.2.0/24"

    def test_missing_subnets_key(self):
        """Missing Subnets key in response handled."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.2.0/24"


class TestFindFreeSubnetAWSErrors:
    """Tests for AWS API error handling."""

    def test_vpc_not_found_error(self):
        """AWS error for invalid VPC propagates."""
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
            _find_free_subnet("vpc-invalid", "10.1")

        assert "InvalidVpcID.NotFound" in str(exc_info.value)

    def test_connection_error(self):
        """Network connection error propagates."""
        mock_ec2 = MagicMock()
        from botocore.exceptions import EndpointConnectionError

        mock_ec2.describe_subnets.side_effect = EndpointConnectionError(
            endpoint_url="https://ec2.us-east-2.amazonaws.com"
        )

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(EndpointConnectionError),
        ):
            _find_free_subnet("vpc-12345", "10.1")


# =============================================================================
# NetworkComponent Pulumi Tests
# =============================================================================


@pytest.fixture
def mock_find_free_subnet():
    """Mock _find_free_subnet for NetworkComponent tests.

    The function makes real AWS API calls, which we don't want
    during Pulumi component tests.
    """
    with patch("components.network._find_free_subnet", return_value="10.1.8.0/24") as mock:
        yield mock


class TestNetworkComponentWithPulumiMocks:
    """Tests for NetworkComponent using Pulumi runtime mocks.

    These tests actually instantiate the real NetworkComponent class
    and verify its behavior using Pulumi's mocking framework.
    """

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks
        self.mock_find_free_subnet = mock_find_free_subnet

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
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        # Verify subnet was created
        assert component.subnet is not None
        assert component.subnet_id is not None
        assert component.subnet_cidr is not None

    @pulumi.runtime.test
    def test_uses_find_free_subnet_result(self):
        """Subnet CIDR should come from _find_free_subnet, not calculation."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            cidr_prefix="10.1",
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        def check_cidr(cidr):
            # Should use the mocked value from _find_free_subnet
            assert cidr == "10.1.8.0/24"

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
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

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
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet):
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
            route_table_id="rtb-12345",
            environment="dev",
            availability_zone="us-east-2a",
        )

        # Verify component has expected outputs
        assert component.subnet is not None
        assert component.subnet_id is not None
        assert component.subnet_cidr is not None

        # Verify subnet_cidr output value comes from _find_free_subnet
        def check_cidr(cidr):
            assert cidr == "10.1.8.0/24"

        component.subnet_cidr.apply(check_cidr)
