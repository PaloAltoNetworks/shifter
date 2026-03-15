"""Network component tests for Shifter Engine.

Unit tests for subnet allocation logic:
- _find_free_subnet: Finds available subnets by querying AWS
- Handles overlapping CIDRs correctly (e.g., /22 blocks)
- CIDR candidate generation for /24 and /28 subnets
- SubnetAllocation table: track, release, drift reconciliation
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from components.network import (
    _find_free_subnet,
    _generate_slash24_candidates,
    _generate_slash28_candidates,
    _publish_subnet_exhaustion_alarm,
    allocate_subnets,
    release_subnet_allocations,
)


@pytest.fixture(autouse=True)
def mock_db_connection():
    """Mock database connection for advisory lock."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("components.network._get_db_connection", return_value=mock_conn):
        yield mock_conn


class TestPublishSubnetExhaustionAlarm:
    """Tests for subnet exhaustion alarm function."""

    def test_publishes_cloudwatch_metric_with_dimensions(self):
        """Alarm publishes CloudWatch metric with VPC and subnet size dimensions."""
        mock_cloudwatch = MagicMock()

        with patch("components.network.boto3.client", return_value=mock_cloudwatch):
            _publish_subnet_exhaustion_alarm("vpc-12345", "10.1", 24)

        mock_cloudwatch.put_metric_data.assert_called_once()
        call_args = mock_cloudwatch.put_metric_data.call_args
        assert call_args[1]["Namespace"] == "Shifter/RangeProvisioning"
        assert call_args[1]["MetricData"][0]["MetricName"] == "SubnetExhaustion"
        dimensions = call_args[1]["MetricData"][0]["Dimensions"]
        assert {"Name": "VpcId", "Value": "vpc-12345"} in dimensions
        assert {"Name": "SubnetSize", "Value": "24"} in dimensions


class TestFindFreeSubnetHappyPath:
    """Happy path tests for _find_free_subnet."""

    def test_finds_first_free_subnet_no_existing(self):
        """No existing subnets, returns first available (.2.0/24)."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.2.0/24"

    def test_skips_existing_subnets(self):
        """Skips existing /24 subnets and finds next free one."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/24"},
                {"CidrBlock": "10.1.3.0/24"},
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.4.0/24"

    def test_finds_gap_in_middle(self):
        """Finds a free subnet in a gap between used ones."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/24"},
                {"CidrBlock": "10.1.3.0/24"},
                {"CidrBlock": "10.1.5.0/24"},
                {"CidrBlock": "10.1.6.0/24"},
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.4.0/24"


class TestFindFreeSubnetOverlappingCIDRs:
    """Tests for handling overlapping CIDRs (the main bug fix)."""

    def test_slash_22_blocks_multiple_slash_24s(self):
        """A /22 subnet blocks multiple /24 candidates."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.2.0/24"},
                {"CidrBlock": "10.1.3.0/24"},
                {"CidrBlock": "10.1.4.0/22"},  # Covers .4, .5, .6, .7
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.8.0/24"

    def test_complex_overlapping_scenario(self):
        """Multiple overlapping subnets of different sizes."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {
            "Subnets": [
                {"CidrBlock": "10.1.0.0/28"},
                {"CidrBlock": "10.1.2.0/24"},
                {"CidrBlock": "10.1.3.0/24"},
                {"CidrBlock": "10.1.4.0/22"},  # Covers .4-.7
                {"CidrBlock": "10.1.8.0/24"},
            ]
        }

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.9.0/24"

    def test_slash_16_blocks_all_candidates(self):
        """A /16 subnet causes no free subnet error."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": [{"CidrBlock": "10.1.0.0/16"}]}

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(RuntimeError, match="No free /24 subnet available"),
        ):
            _find_free_subnet("vpc-12345", "10.1")


class TestFindFreeSubnetExhaustion:
    """Tests for subnet exhaustion scenarios."""

    def test_exhaustion_publishes_alarm(self):
        """Subnet exhaustion triggers CloudWatch alarm metric."""
        mock_ec2 = MagicMock()
        mock_cloudwatch = MagicMock()
        all_subnets = [{"CidrBlock": f"10.1.{i}.0/24"} for i in range(2, 255)]
        mock_ec2.describe_subnets.return_value = {"Subnets": all_subnets}

        def client_factory(service, **kwargs):
            return mock_ec2 if service == "ec2" else mock_cloudwatch

        with (
            patch("components.network.boto3.client", side_effect=client_factory),
            pytest.raises(RuntimeError),
        ):
            _find_free_subnet("vpc-exhausted", "10.1")

        mock_cloudwatch.put_metric_data.assert_called_once()


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

        assert result == "10.1.3.0/24"

    def test_vpc_not_found_error_propagates(self):
        """AWS error for invalid VPC propagates."""
        mock_ec2 = MagicMock()
        from botocore.exceptions import ClientError

        mock_ec2.describe_subnets.side_effect = ClientError(
            {"Error": {"Code": "InvalidVpcID.NotFound", "Message": "VPC not found"}},
            "DescribeSubnets",
        )

        with (
            patch("components.network.boto3.client", return_value=mock_ec2),
            pytest.raises(ClientError),
        ):
            _find_free_subnet("vpc-invalid", "10.1")


class TestGenerateSlash24Candidates:
    """Tests for /24 CIDR candidate generation."""

    def test_generates_correct_range(self):
        """Should generate .2.0/24 through .254.0/24."""
        candidates = _generate_slash24_candidates("10.1")
        assert candidates[0] == "10.1.2.0/24"
        assert candidates[-1] == "10.1.254.0/24"
        assert len(candidates) == 253


class TestGenerateSlash28Candidates:
    """Tests for /28 CIDR candidate generation."""

    def test_correct_step_size(self):
        """Should step by 16 in fourth octet."""
        candidates = _generate_slash28_candidates("10.1")
        assert candidates[0] == "10.1.2.0/28"
        assert candidates[1] == "10.1.2.16/28"
        assert candidates[15] == "10.1.2.240/28"
        assert candidates[16] == "10.1.3.0/28"

    def test_total_candidates(self):
        """Should generate correct number of /28 blocks."""
        candidates = _generate_slash28_candidates("10.1")
        assert len(candidates) == 253 * 16


class TestFindFreeSubnetSlash28:
    """/28 subnet allocation tests."""

    def test_finds_first_free_slash28(self):
        """No existing subnets, returns first /28."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.2.0/28"

    def test_skips_existing_slash28(self):
        """Skips occupied /28 and finds next free."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": [{"CidrBlock": "10.1.2.0/28"}]}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.2.16/28"

    def test_slash24_blocks_all_slash28s_within(self):
        """A /24 blocks all /28s within it."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": [{"CidrBlock": "10.1.2.0/24"}]}

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.3.0/28"

    def test_invalid_subnet_size_raises(self):
        """Invalid subnet_size raises ValueError."""
        with pytest.raises(ValueError, match="subnet_size must be 24 or 28"):
            _find_free_subnet("vpc-12345", "10.1", subnet_size=26)


class TestAllocateSubnetsReservation:
    """Tests for SubnetAllocation table integration in allocate_subnets."""

    def test_allocate_subnets_reserves_in_table(self, mock_db_connection):
        """After allocation, INSERT rows are executed for each CIDR."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        # Track SQL executed on the cursor
        mock_cursor = MagicMock()
        mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = allocate_subnets(
                "vpc-123",
                "10.1",
                count=2,
                subnet_size=28,
                range_id=42,
                request_id="req-abc",
            )

        assert len(result) == 2
        assert result[0] == "10.1.2.0/28"
        assert result[1] == "10.1.2.16/28"

        # Verify INSERT was called for each CIDR (on the connection's cursor)
        all_sql = [c[0][0] for c in mock_cursor.execute.call_args_list if c[0] and isinstance(c[0][0], str)]
        insert_calls = [s for s in all_sql if "INSERT INTO engine_subnetallocation" in s]
        assert len(insert_calls) == 2

    def test_allocate_skips_tracked_cidrs(self, mock_db_connection):
        """CIDR in allocation table is skipped even if not yet in AWS."""
        mock_ec2 = MagicMock()
        mock_ec2.describe_subnets.return_value = {"Subnets": []}

        # Simulate allocation table returning a tracked CIDR
        mock_cursor = MagicMock()
        mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)

        # The SELECT returns 10.1.2.0/28 as tracked
        mock_cursor.fetchall.return_value = [("10.1.2.0/28",)]

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = allocate_subnets(
                "vpc-123",
                "10.1",
                count=1,
                subnet_size=28,
                range_id=42,
                request_id="req-abc",
            )

        # Should skip the tracked CIDR and pick the next one
        assert result == ["10.1.2.16/28"]

    def test_drift_reconciliation(self, mock_db_connection):
        """AWS subnets not in the table are inserted during allocation."""
        mock_ec2 = MagicMock()
        # AWS has a subnet that's not in the allocation table
        mock_ec2.describe_subnets.return_value = {"Subnets": [{"CidrBlock": "10.1.2.0/28"}]}

        mock_cursor = MagicMock()
        mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        # Table is empty
        mock_cursor.fetchall.return_value = []

        with patch("components.network.boto3.client", return_value=mock_ec2):
            result = allocate_subnets(
                "vpc-123",
                "10.1",
                count=1,
                subnet_size=28,
                range_id=42,
                request_id="req-abc",
            )

        # Should skip the AWS subnet and pick the next one
        assert result == ["10.1.2.16/28"]

        # Verify the drift subnet was inserted into the table
        insert_calls = [
            c
            for c in mock_cursor.execute.call_args_list
            if c[0] and isinstance(c[0][0], str) and "INSERT INTO engine_subnetallocation" in c[0][0]
        ]
        # At least 2 inserts: 1 for drift reconciliation + 1 for the new allocation
        assert len(insert_calls) >= 2


class TestReleaseSubnetAllocations:
    """Tests for release_subnet_allocations."""

    def test_release_deletes_rows(self, mock_db_connection):
        """release_subnet_allocations DELETEs rows for the request."""
        mock_cursor = MagicMock()
        mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)

        release_subnet_allocations("req-abc")

        # Verify DELETE was executed
        delete_calls = [
            c
            for c in mock_cursor.execute.call_args_list
            if c[0] and isinstance(c[0][0], str) and "DELETE FROM engine_subnetallocation" in c[0][0]
        ]
        assert len(delete_calls) == 1
        params = delete_calls[0][0][1]
        assert params[0] == "req-abc"

        mock_db_connection.commit.assert_called()


class TestDBConnectionRequired:
    """Tests that allocation fails hard when DB is unreachable."""

    def test_raises_without_db(self):
        """Allocation must fail when DB is unreachable — no silent fallback."""
        import psycopg

        with (
            patch("components.network._get_db_connection", side_effect=psycopg.Error("conn refused")),
            pytest.raises(psycopg.Error),
        ):
            allocate_subnets(
                "vpc-123",
                "10.1",
                count=1,
                subnet_size=28,
                range_id=42,
                request_id="req-abc",
            )
