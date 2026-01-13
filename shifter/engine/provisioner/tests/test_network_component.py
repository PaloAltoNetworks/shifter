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

from components.network import (
    _find_free_subnet,
    _generate_slash24_candidates,
    _generate_slash28_candidates,
    _publish_subnet_exhaustion_alarm,
)

# =============================================================================
# Unit Tests for _publish_subnet_exhaustion_alarm
# =============================================================================


class TestPublishSubnetExhaustionAlarm:
    """Tests for the subnet exhaustion alarm function."""

    def test_publishes_cloudwatch_metric(self):
        """Alarm function publishes a CloudWatch metric."""
        mock_cloudwatch = MagicMock()

        with patch("components.network.boto3.client", return_value=mock_cloudwatch):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1", 24)

        mock_cloudwatch.put_metric_data.assert_called_once()
        call_args = mock_cloudwatch.put_metric_data.call_args
        assert call_args[1]["Namespace"] == "Shifter/RangeProvisioning"
        assert call_args[1]["MetricData"][0]["MetricName"] == "SubnetExhaustion"
        assert call_args[1]["MetricData"][0]["Value"] == 1

    def test_metric_includes_vpc_dimension(self):
        """Metric includes VPC ID as a dimension."""
        mock_cloudwatch = MagicMock()

        with patch("components.network.boto3.client", return_value=mock_cloudwatch):
            _publish_subnet_exhaustion_alarm("vpc-my-test-vpc", "10.1", 24)

        call_args = mock_cloudwatch.put_metric_data.call_args
        dimensions = call_args[1]["MetricData"][0]["Dimensions"]
        assert {"Name": "VpcId", "Value": "vpc-my-test-vpc"} in dimensions

    def test_metric_includes_subnet_size_dimension(self):
        """Metric includes SubnetSize as a dimension."""
        mock_cloudwatch = MagicMock()

        with patch("components.network.boto3.client", return_value=mock_cloudwatch):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1", 28)

        call_args = mock_cloudwatch.put_metric_data.call_args
        dimensions = call_args[1]["MetricData"][0]["Dimensions"]
        assert {"Name": "SubnetSize", "Value": "28"} in dimensions

    def test_uses_aws_region_env_var(self):
        """Uses AWS_REGION environment variable."""
        mock_cloudwatch = MagicMock()

        with (
            patch("components.network.boto3.client", return_value=mock_cloudwatch) as mock_client,
            patch.dict("os.environ", {"AWS_REGION": "eu-west-1"}),
        ):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1", 24)

        mock_client.assert_called_with("cloudwatch", region_name="eu-west-1")

    def test_defaults_to_us_east_2(self):
        """Defaults to us-east-2 if AWS_REGION not set."""
        mock_cloudwatch = MagicMock()

        with (
            patch("components.network.boto3.client", return_value=mock_cloudwatch) as mock_client,
            patch.dict("os.environ", {}, clear=True),
        ):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1", 24)

        mock_client.assert_called_with("cloudwatch", region_name="us-east-2")


# =============================================================================
# Unit Tests for _find_free_subnet
# =============================================================================


@pytest.fixture(autouse=True)
def mock_db_connection():
    """Mock the database connection for advisory lock.

    The advisory lock was added to prevent concurrent subnet allocations.
    In tests, we mock the DB connection to avoid needing a real database.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("components.network._get_db_connection", return_value=mock_conn):
        yield mock_conn


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
# Unit Tests for CIDR Candidate Generators
# =============================================================================


class TestGenerateSlash24Candidates:
    """Tests for /24 CIDR candidate generation."""

    def test_generates_correct_range(self):
        """Should generate .2.0/24 through .254.0/24."""
        candidates = _generate_slash24_candidates("10.1")
        assert candidates[0] == "10.1.2.0/24"
        assert candidates[-1] == "10.1.254.0/24"
        assert len(candidates) == 253  # 2-254 inclusive

    def test_different_prefix(self):
        """Works with different CIDR prefixes."""
        candidates = _generate_slash24_candidates("172.16")
        assert candidates[0] == "172.16.2.0/24"
        assert "172.16.100.0/24" in candidates


class TestGenerateSlash28Candidates:
    """Tests for /28 CIDR candidate generation."""

    def test_first_candidate_starts_at_2_0(self):
        """First /28 should be 10.1.2.0/28 (skip .0 and .1)."""
        candidates = _generate_slash28_candidates("10.1")
        assert candidates[0] == "10.1.2.0/28"

    def test_correct_step_size(self):
        """Should step by 16 in fourth octet."""
        candidates = _generate_slash28_candidates("10.1")
        # First 16 candidates in .2.x
        assert candidates[0] == "10.1.2.0/28"
        assert candidates[1] == "10.1.2.16/28"
        assert candidates[2] == "10.1.2.32/28"
        assert candidates[15] == "10.1.2.240/28"
        # Then moves to .3.x
        assert candidates[16] == "10.1.3.0/28"

    def test_total_candidates(self):
        """Should generate correct number of /28 blocks."""
        candidates = _generate_slash28_candidates("10.1")
        # 253 third octets (2-254) * 16 /28 blocks each = 4048
        assert len(candidates) == 253 * 16

    def test_all_valid_cidrs(self):
        """All candidates should be valid /28 CIDRs."""
        import ipaddress

        candidates = _generate_slash28_candidates("10.1")
        for cidr in candidates[:100]:  # Check first 100
            network = ipaddress.ip_network(cidr)
            assert network.prefixlen == 28


class TestFindFreeSubnetSlash28:
    """/28 subnet allocation tests."""

    def test_finds_first_free_slash28(self):
        """No existing subnets, returns first /28 (.2.0/28)."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.2.0/28"

    def test_skips_existing_slash28(self):
        """Skips occupied /28 and finds next free."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/28"},
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.2.16/28"

    def test_skips_multiple_slash28s(self):
        """Skips multiple occupied /28s."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/28"},
                {"CidrBlock": "10.1.2.16/28"},
                {"CidrBlock": "10.1.2.32/28"},
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.2.48/28"

    def test_slash28_overlaps_with_larger_block(self):
        """A /24 blocks all /28s within it."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/24"},  # Blocks all .2.x/28
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.3.0/28"

    def test_invalid_subnet_size_raises(self):
        """Invalid subnet_size raises ValueError."""
        with pytest.raises(ValueError, match="subnet_size must be 24 or 28"):
            _find_free_subnet("vpc-12345", "10.1", subnet_size=26)


# =============================================================================
# NetworkComponent Pulumi Tests
# =============================================================================


@pytest.fixture
def mock_find_free_subnet():
    """Mock _find_free_subnet for NetworkComponent tests."""
    with patch("components.network._find_free_subnet", return_value="10.1.8.0/24") as mock:
        yield mock


class TestNetworkComponentWithPulumiMocks:
    """Tests for NetworkComponent using Pulumi runtime mocks."""

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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        # Verify subnet was created
        assert component.subnet is not None
        assert component.subnet_id is not None
        assert component.subnet_cidr is not None

    @pulumi.runtime.test
    def test_creates_security_group(self):
        """NetworkComponent should create a security group."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        assert component.security_group is not None
        assert component.security_group_id is not None

    @pulumi.runtime.test
    def test_creates_route_table(self):
        """NetworkComponent should create a route table."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        assert component.route_table is not None
        assert component.route_table_id is not None

    @pulumi.runtime.test
    def test_uses_find_free_subnet_result(self):
        """Subnet CIDR should come from _find_free_subnet."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        def check_cidr(cidr):
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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-west-2b",
            request_uuid="req-test-123",
        )

        def check_az(az):
            assert az == "us-west-2b"

        component.subnet.availability_zone.apply(check_az)

    @pulumi.runtime.test
    def test_subnet_has_correct_name_tag_legacy(self):
        """Subnet without subnet_name uses legacy naming."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        def check_tags(tags):
            assert tags.get("Name") == "shifter-range-42"

        component.subnet.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_subnet_has_correct_name_tag_with_subnet_name(self):
        """Subnet with subnet_name uses new naming convention."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            subnet_name="attack",
            subnet_uuid="uuid-attack-123",
            request_uuid="req-test-123",
        )

        def check_tags(tags):
            assert tags.get("Name") == "shifter-attack-1"

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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        def check_tags(tags):
            assert tags.get("shifter:range_id") == "42"
            assert tags.get("shifter:user_id") == "1"
            assert tags.get("shifter:environment") == "dev"
            assert tags.get("shifter:system") == "shifter"
            assert tags.get("ManagedBy") == "pulumi"

        component.subnet.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_subnet_with_optional_tags(self):
        """Subnet with optional tags includes them."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            subnet_name="attack",
            subnet_uuid="uuid-123",
            request_uuid="req-456",
        )

        def check_tags(tags):
            assert tags.get("shifter:subnet_name") == "attack"
            assert tags.get("shifter:subnet_uuid") == "uuid-123"
            assert tags.get("shifter:request_uuid") == "req-456"

        component.subnet.tags.apply(check_tags)

    @pulumi.runtime.test
    def test_outputs_are_registered(self):
        """NetworkComponent should register all outputs."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        # Verify all outputs exist
        assert hasattr(component, "subnet_id")
        assert hasattr(component, "subnet_cidr")
        assert hasattr(component, "security_group_id")
        assert hasattr(component, "route_table_id")
        assert hasattr(component, "gwlb_endpoint_id")

    @pulumi.runtime.test
    def test_no_gwlb_endpoint_without_service_name(self):
        """No GWLB endpoint when gwlb_service_name not provided."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        assert component.gwlb_endpoint is None


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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
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
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        # Verify component has expected outputs
        assert component.subnet is not None
        assert component.subnet_id is not None
        assert component.subnet_cidr is not None
        assert component.security_group is not None
        assert component.security_group_id is not None
        assert component.route_table is not None
        assert component.route_table_id is not None

        # Verify subnet_cidr output value comes from _find_free_subnet
        def check_cidr(cidr):
            assert cidr == "10.1.8.0/24"

        component.subnet_cidr.apply(check_cidr)


class TestGWLBEndpointCreation:
    """Tests for GWLB endpoint creation in NetworkComponent."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks, mock_find_free_subnet):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_creates_gwlb_endpoint_when_service_name_provided(self):
        """GWLB endpoint created when gwlb_service_name is provided."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            gwlb_service_name="com.amazonaws.vpce.us-east-2.vpce-svc-123",
            request_uuid="req-test-123",
        )

        assert component.gwlb_endpoint is not None
        assert component.gwlb_endpoint_id is not None

    @pulumi.runtime.test
    def test_gwlb_endpoint_id_is_empty_string_when_no_service_name(self):
        """gwlb_endpoint_id returns empty string when no endpoint created."""
        from components.network import NetworkComponent

        component = NetworkComponent(
            name="test-network",
            range_id=42,
            user_id=1,
            vpc_id="vpc-12345",
            vpc_cidr="10.1.0.0/16",
            cidr_prefix="10.1",
            environment="dev",
            availability_zone="us-east-2a",
            request_uuid="req-test-123",
        )

        def check_empty(endpoint_id):
            assert endpoint_id == ""

        component.gwlb_endpoint_id.apply(check_empty)


class TestSubnetSizeParameter:
    """Tests for subnet_size parameter in NetworkComponent."""

    @pytest.fixture(autouse=True)
    def setup_pulumi_mocks(self, pulumi_mocks):
        """Set up Pulumi mocks for each test."""
        self.mocks = pulumi_mocks

    @pulumi.runtime.test
    def test_slash28_subnet_creation(self):
        """NetworkComponent creates /28 subnet when subnet_size=28."""
        with patch("components.network._find_free_subnet", return_value="10.1.2.0/28"):
            from components.network import NetworkComponent

            component = NetworkComponent(
                name="test-network",
                range_id=42,
                user_id=1,
                vpc_id="vpc-12345",
                vpc_cidr="10.1.0.0/16",
                cidr_prefix="10.1",
                environment="dev",
                availability_zone="us-east-2a",
                subnet_size=28,
                request_uuid="req-test-123",
            )

            def check_cidr(cidr):
                assert cidr == "10.1.2.0/28"

            component.subnet_cidr.apply(check_cidr)

    @pulumi.runtime.test
    def test_slash24_subnet_creation_default(self):
        """NetworkComponent creates /24 subnet by default."""
        with patch("components.network._find_free_subnet", return_value="10.1.2.0/24"):
            from components.network import NetworkComponent

            component = NetworkComponent(
                name="test-network",
                range_id=42,
                user_id=1,
                vpc_id="vpc-12345",
                vpc_cidr="10.1.0.0/16",
                cidr_prefix="10.1",
                environment="dev",
                availability_zone="us-east-2a",
                request_uuid="req-test-123",
            )

            def check_cidr(cidr):
                assert cidr == "10.1.2.0/24"

            component.subnet_cidr.apply(check_cidr)
