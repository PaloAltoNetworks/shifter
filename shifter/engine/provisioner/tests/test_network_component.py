"""Network component tests for Shifter Engine.

Unit tests for subnet allocation logic:
- _find_free_subnet: Finds available subnets via the cloud network adapter
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
def mock_db_connection(request):
    """Mock database connection for advisory lock."""
    if request.node.get_closest_marker("exercise_real_db_connection"):
        yield None
        return

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("components.network._get_db_connection", return_value=mock_conn):
        yield mock_conn


@pytest.fixture
def mock_network_inventory():
    """Mock the provider network inventory adapter."""
    inventory = MagicMock()
    inventory.list_subnet_cidrs.return_value = []
    with patch("components.network._get_network_inventory", return_value=inventory):
        yield inventory


class TestPublishSubnetExhaustionAlarm:
    """Tests for subnet exhaustion alarm function."""

    def test_delegates_to_provider_inventory(self, mock_network_inventory):
        """Alarm publishing delegates to the active network inventory adapter."""
        _publish_subnet_exhaustion_alarm("vpc-12345", "10.1", 24)

        mock_network_inventory.publish_subnet_exhaustion_alarm.assert_called_once_with("vpc-12345", "10.1", 24)


class TestFindFreeSubnetHappyPath:
    """Happy path tests for _find_free_subnet."""

    def test_finds_first_free_subnet_no_existing(self, mock_network_inventory):
        """No existing subnets, returns first available (.2.0/24)."""
        mock_network_inventory.list_subnet_cidrs.return_value = []
        result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.2.0/24"

    def test_skips_existing_subnets(self, mock_network_inventory):
        """Skips existing /24 subnets and finds next free one."""
        mock_network_inventory.list_subnet_cidrs.return_value = [
            "10.1.2.0/24",
            "10.1.3.0/24",
        ]
        result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.4.0/24"

    def test_finds_gap_in_middle(self, mock_network_inventory):
        """Finds a free subnet in a gap between used ones."""
        mock_network_inventory.list_subnet_cidrs.return_value = [
            "10.1.2.0/24",
            "10.1.3.0/24",
            "10.1.5.0/24",
            "10.1.6.0/24",
        ]
        result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.4.0/24"


class TestFindFreeSubnetOverlappingCIDRs:
    """Tests for handling overlapping CIDRs (the main bug fix)."""

    def test_slash_22_blocks_multiple_slash_24s(self, mock_network_inventory):
        """A /22 subnet blocks multiple /24 candidates."""
        mock_network_inventory.list_subnet_cidrs.return_value = [
            "10.1.2.0/24",
            "10.1.3.0/24",
            "10.1.4.0/22",
        ]
        result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.8.0/24"

    def test_complex_overlapping_scenario(self, mock_network_inventory):
        """Multiple overlapping subnets of different sizes."""
        mock_network_inventory.list_subnet_cidrs.return_value = [
            "10.1.0.0/28",
            "10.1.2.0/24",
            "10.1.3.0/24",
            "10.1.4.0/22",
            "10.1.8.0/24",
        ]
        result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.9.0/24"

    def test_slash_16_blocks_all_candidates(self, mock_network_inventory):
        """A /16 subnet causes no free subnet error."""
        mock_network_inventory.list_subnet_cidrs.return_value = ["10.1.0.0/16"]

        with pytest.raises(RuntimeError, match="No free /24 subnet available"):
            _find_free_subnet("vpc-12345", "10.1")


class TestFindFreeSubnetExhaustion:
    """Tests for subnet exhaustion scenarios."""

    def test_exhaustion_publishes_alarm(self, mock_network_inventory):
        """Subnet exhaustion triggers CloudWatch alarm metric."""
        mock_network_inventory.list_subnet_cidrs.return_value = [f"10.1.{i}.0/24" for i in range(2, 255)]

        with pytest.raises(RuntimeError):
            _find_free_subnet("vpc-exhausted", "10.1")

        mock_network_inventory.publish_subnet_exhaustion_alarm.assert_called_once()


class TestFindFreeSubnetEdgeCases:
    """Edge case tests for _find_free_subnet."""

    def test_different_cidr_prefix(self, mock_network_inventory):
        """Works with different CIDR prefixes."""
        mock_network_inventory.list_subnet_cidrs.return_value = []
        result = _find_free_subnet("vpc-12345", "172.16")

        assert result == "172.16.2.0/24"

    def test_invalid_cidr_in_cloud_response_ignored(self, mock_network_inventory):
        """Invalid CIDRs from the cloud adapter are gracefully ignored."""
        mock_network_inventory.list_subnet_cidrs.return_value = [
            "invalid-cidr",
            "10.1.2.0/24",
        ]
        result = _find_free_subnet("vpc-12345", "10.1")

        assert result == "10.1.3.0/24"

    def test_inventory_error_propagates(self, mock_network_inventory):
        """Cloud inventory errors propagate to the allocator."""
        mock_network_inventory.list_subnet_cidrs.side_effect = RuntimeError("network lookup failed")

        with pytest.raises(RuntimeError, match="network lookup failed"):
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

    def test_finds_first_free_slash28(self, mock_network_inventory):
        """No existing subnets, returns first /28."""
        mock_network_inventory.list_subnet_cidrs.return_value = []
        result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.2.0/28"

    def test_skips_existing_slash28(self, mock_network_inventory):
        """Skips occupied /28 and finds next free."""
        mock_network_inventory.list_subnet_cidrs.return_value = ["10.1.2.0/28"]
        result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.2.16/28"

    def test_slash24_blocks_all_slash28s_within(self, mock_network_inventory):
        """A /24 blocks all /28s within it."""
        mock_network_inventory.list_subnet_cidrs.return_value = ["10.1.2.0/24"]
        result = _find_free_subnet("vpc-12345", "10.1", subnet_size=28)

        assert result == "10.1.3.0/28"

    def test_invalid_subnet_size_raises(self):
        """Invalid subnet_size raises ValueError."""
        with pytest.raises(ValueError, match="subnet_size must be 24 or 28"):
            _find_free_subnet("vpc-12345", "10.1", subnet_size=26)


class TestAllocateSubnetsReservation:
    """Tests for SubnetAllocation table integration in allocate_subnets."""

    def test_allocate_subnets_reserves_in_table(self, mock_db_connection, mock_network_inventory):
        """After allocation, INSERT rows are executed for each CIDR."""
        mock_network_inventory.list_subnet_cidrs.return_value = []

        # Track SQL executed on the cursor
        mock_cursor = MagicMock()
        mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)

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

    def test_allocate_skips_tracked_cidrs(self, mock_db_connection, mock_network_inventory):
        """CIDR in allocation table is skipped even if not yet in AWS."""
        mock_network_inventory.list_subnet_cidrs.return_value = []

        # Simulate allocation table returning a tracked CIDR
        mock_cursor = MagicMock()
        mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)

        # The SELECT returns 10.1.2.0/28 as tracked
        mock_cursor.fetchall.return_value = [("10.1.2.0/28",)]

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

    def test_drift_reconciliation(self, mock_db_connection, mock_network_inventory):
        """Cloud subnets not in the table are inserted during allocation."""
        mock_network_inventory.list_subnet_cidrs.return_value = ["10.1.2.0/28"]

        mock_cursor = MagicMock()
        mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        # Table is empty
        mock_cursor.fetchall.return_value = []

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


class TestDBConnectionAuthMode:
    """Tests for provider-neutral DB auth mode in _get_db_connection."""

    @pytest.mark.exercise_real_db_connection
    @patch.dict(
        "os.environ",
        {
            "CLOUD_PROVIDER": "gcp",
            "DB_HOST": "db.internal",
            "DB_PORT": "5432",
            "DB_USER": "shifter",
            "DB_NAME": "shifter",
        },
        clear=True,
    )
    def test_cloud_db_auth_does_not_require_aws_region(self):
        """Cloud DB auth should work without AWS_REGION when using the adapter seam."""
        from components.network import _get_db_connection

        mock_auth = MagicMock()
        mock_auth.generate_auth_token.return_value = "gcp-auth-token"

        with (
            patch("cloud.get_db_auth", return_value=mock_auth),
            patch("components.network.psycopg.connect", return_value=MagicMock()) as mock_connect,
        ):
            _get_db_connection()

        mock_auth.generate_auth_token.assert_called_once_with(
            hostname="db.internal",
            port=5432,
            username="shifter",
        )
        assert mock_connect.call_args.kwargs["sslmode"] == "require"
