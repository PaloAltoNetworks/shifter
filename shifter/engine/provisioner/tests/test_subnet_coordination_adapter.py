"""Provisioner adapter over the Engine subnet-coordination routines (#1838).

The provisioner no longer touches ``engine_subnetallocation``: it observes the
provider network, hands that observation to the Engine-owned routine, and takes
back the CIDRs the routine reserved. These tests pin the adapter's side of that
contract -- what it sends, what it does with a refusal, and what it must never
put in a log line.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.subnet_coordination import (
    REASON_EXHAUSTED,
    REASON_STALE_GENERATION,
    SubnetCoordinationError,
)

from components.network import (
    read_range_subnets,
    release_range_subnets,
    reserve_range_subnets,
)

OPERATION_ID = str(uuid4())
REQUEST_ID = str(uuid4())
NETWORK_ID = "range-network-test"
NETWORK_CIDR = "10.1.0.0/16"


class _FakeError(Exception):
    """Stands in for a psycopg error carrying a SQLSTATE."""

    def __init__(self, sqlstate: str):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.fixture
def cursor(mock_db_connection):
    """Return the cursor the adapter will execute against."""
    cur = MagicMock()
    mock_db_connection.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    return cur


@pytest.fixture(autouse=True)
def mock_db_connection():
    """Return the connection the adapter gets, patching only the driver boundary.

    ``psycopg.connect`` is the real process boundary; everything between it and
    the adapter -- including the canonical connection factory -- runs for real, so
    a regression in that path is visible here instead of mocked away.
    """
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    db_env = {
        "DB_HOST": "db.internal",
        "DB_PORT": "5432",
        "DB_USER": "shifter",
        "DB_NAME": "shifter",
        "DB_PASSWORD": "local-dev",
    }
    with patch.dict("os.environ", db_env, clear=False), patch("psycopg.connect", return_value=conn):
        yield conn


class _FakeInventoryClients:
    """Records boto3 calls so the real AWS inventory adapter can be driven.

    Patching ``boto3.client`` rather than the first-party factory keeps the whole
    observation path -- provider resolution, the AWS adapter, its error mapping --
    inside the test, so a break anywhere along it shows up here.
    """

    def __init__(self):
        self.subnet_cidrs: list[str] = []
        self.describe_error: Exception | None = None
        self.metrics: list[dict] = []

    def describe_subnets(self, **_kwargs):
        if self.describe_error is not None:
            raise self.describe_error
        return {"Subnets": [{"CidrBlock": cidr} for cidr in self.subnet_cidrs]}

    def put_metric_data(self, **kwargs):
        self.metrics.append(kwargs)

    def __call__(self, service_name, **_kwargs):
        return self


@pytest.fixture
def inventory():
    """Drive the real provider inventory adapter through the boto3 boundary."""
    clients = _FakeInventoryClients()
    env = {"CLOUD_PROVIDER": "aws", "AWS_REGION": "us-east-2"}
    with patch.dict("os.environ", env, clear=False), patch("boto3.client", clients):
        yield clients


def _reserve(**overrides):
    kwargs = {
        "operation_id": OPERATION_ID,
        "request_id": REQUEST_ID,
        "network_id": NETWORK_ID,
        "network_cidr": NETWORK_CIDR,
        "subnets": ("0:attack", "1:victim"),
    }
    kwargs.update(overrides)
    return reserve_range_subnets(**kwargs)


class TestReserve:
    def test_returns_the_reserved_cidrs_in_order(self, cursor, inventory):
        cursor.fetchall.return_value = [(2, "10.1.2.16/28"), (1, "10.1.2.0/28")]

        assert _reserve() == ("10.1.2.0/28", "10.1.2.16/28")

    def test_sends_the_provider_observation_to_the_routine(self, cursor, inventory):
        # The routine cannot see the cloud; if the adapter dropped the
        # observation, drift repair would silently stop happening.
        inventory.subnet_cidrs = ["10.1.2.0/28", "10.1.3.0/28"]
        cursor.fetchall.return_value = [(1, "10.1.4.0/28"), (2, "10.1.4.16/28")]

        _reserve()

        params = cursor.execute.call_args[0][1]
        assert params[-2] == "{10.1.2.0/28,10.1.3.0/28}"

    def test_an_unparseable_provider_entry_aborts_the_reservation(self, cursor, inventory):
        # A dropped entry is indistinguishable from "that subnet does not exist",
        # which is how the allocator would come to hand out an occupied CIDR. An
        # incomplete observation must stop the reservation, not narrow it.
        from cloud.exceptions import CloudNetworkInventoryError

        inventory.subnet_cidrs = ["10.1.2.0/28", "garbage"]

        with pytest.raises(CloudNetworkInventoryError):
            _reserve()

        cursor.execute.assert_not_called()

    def test_ipv6_networks_are_omitted_without_aborting(self, cursor, inventory):
        # Allocation carves IPv4 only, and an IPv6 network cannot overlap an IPv4
        # candidate, so omitting it provably cannot mask a conflict.
        inventory.subnet_cidrs = ["10.1.2.0/28", "2001:db8::/32"]
        cursor.fetchall.return_value = [(1, "10.1.3.0/28"), (2, "10.1.3.16/28")]

        _reserve()

        params = cursor.execute.call_args[0][1]
        assert params[-2] == "{10.1.2.0/28}"

    def test_commits_so_the_reservation_outlives_the_lock(self, cursor, inventory, mock_db_connection):
        cursor.fetchall.return_value = [(1, "10.1.2.0/28"), (2, "10.1.2.16/28")]

        _reserve()

        mock_db_connection.commit.assert_called()

    def test_publishes_the_exhaustion_alarm_and_fails(self, cursor, inventory):
        # Exhaustion is an infrastructure alert, not just a failed provision:
        # without free subnets nobody can launch a range.
        cursor.execute.side_effect = _FakeError("SH002")

        with pytest.raises(SubnetCoordinationError) as exc:
            _reserve()

        assert REASON_EXHAUSTED in str(exc.value)
        assert [m["Namespace"] for m in inventory.metrics] == ["Shifter/RangeProvisioning"]

    def test_does_not_publish_the_alarm_for_an_unrelated_refusal(self, cursor, inventory):
        cursor.execute.side_effect = _FakeError("SH003")

        with pytest.raises(SubnetCoordinationError) as exc:
            _reserve()

        assert REASON_STALE_GENERATION in str(exc.value)
        assert inventory.metrics == []

    def test_an_unrecognized_database_failure_is_not_translated(self, cursor, inventory):
        # A connection or infrastructure fault must not be laundered into a
        # domain reason code that reads like a refusal.
        cursor.execute.side_effect = _FakeError("08006")

        with pytest.raises(_FakeError):
            _reserve()

    def test_sends_the_reservation_shape_fingerprint(self, cursor, inventory):
        # The routine compares this to decide whether a retry is the same
        # request; an adapter that stopped sending it would make every retry
        # look like a first reservation.
        cursor.fetchall.return_value = [(1, "10.1.2.0/28"), (2, "10.1.2.16/28")]

        _reserve()

        assert cursor.execute.call_args[0][1][-1].startswith("sha256:")

    def test_a_missing_operation_generation_fails_closed(self, inventory):
        # No fallback: without a current generation the routine cannot fence the
        # reservation, so the provision must stop here rather than reserve
        # untracked capacity.
        with pytest.raises(SubnetCoordinationError):
            _reserve(operation_id=None)

    def test_does_not_log_the_allocated_cidrs(self, cursor, inventory, caplog):
        # CIDRs are infrastructure topology and are not needed for correlation.
        cursor.fetchall.return_value = [(1, "10.1.2.0/28"), (2, "10.1.2.16/28")]

        with caplog.at_level("DEBUG"):
            _reserve()

        assert "10.1.2.0/28" not in caplog.text


class TestReadAndRelease:
    def test_read_returns_the_existing_reservation(self, cursor):
        cursor.fetchall.return_value = [(1, "10.1.2.0/28"), (2, "10.1.2.16/28")]

        result = read_range_subnets(operation_id=OPERATION_ID, request_id=REQUEST_ID)

        assert result == ("10.1.2.0/28", "10.1.2.16/28")

    def test_read_returns_empty_when_nothing_is_reserved(self, cursor):
        cursor.fetchall.return_value = []

        assert read_range_subnets(operation_id=OPERATION_ID, request_id=REQUEST_ID) == ()

    def test_release_reports_how_many_rows_went(self, cursor, mock_db_connection):
        cursor.fetchone.return_value = (2,)

        assert release_range_subnets(operation_id=OPERATION_ID, request_id=REQUEST_ID) == 2
        mock_db_connection.commit.assert_called()


class TestNoDirectTableAccessRemains:
    def test_the_network_package_issues_no_allocation_table_sql(self):
        """The grants are gone, so any surviving direct SQL is dead on arrival.

        Asserting it here means a well-meaning re-introduction fails in the unit
        lane rather than at provision time in a deployed environment. The pattern
        matches the table in SQL position rather than anywhere in the file, so
        prose about the boundary stays allowed and a real statement does not.
        """
        statement = re.compile(
            r"\b(from|into|update|table|join)\s+engine_subnetallocation\b",
            re.IGNORECASE,
        )
        package = Path(__file__).parent.parent / "components" / "network"

        offenders = [path.name for path in package.glob("*.py") if statement.search(path.read_text())]

        assert offenders == []
