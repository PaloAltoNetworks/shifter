"""Network component tests for Shifter Engine.

Unit tests for what the provisioner still owns after the #1838 coordination
cutover: observing the provider network, raising the exhaustion alarm, and
reaching the database through the canonical connection factory. Reservation
policy itself -- candidate selection, drift merge, locking, release -- now lives
in the Engine coordination routines and is proven against real PostgreSQL in
``tests/engine/services/test_subnet_coordination_postgres.py``; the adapter's side
of that boundary is covered by ``tests/test_subnet_coordination_adapter.py``.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from components.network import (
    _get_db_connection,
    _get_existing_subnets,
    _publish_subnet_exhaustion_alarm,
)


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

    def test_alarm_failure_does_not_mask_the_exhaustion(self, mock_network_inventory):
        """A failed alarm must not replace the exhaustion the caller is reporting."""
        from cloud.exceptions import CloudNetworkInventoryError

        mock_network_inventory.publish_subnet_exhaustion_alarm.side_effect = CloudNetworkInventoryError("no topic")

        _publish_subnet_exhaustion_alarm("vpc-12345", "10.1", 28)


class TestGetExistingSubnets:
    """Tests for the provider observation handed to the coordination routine."""

    def test_returns_the_provider_subnets(self, mock_network_inventory):
        mock_network_inventory.list_subnet_cidrs.return_value = ["10.1.2.0/24", "10.1.3.0/28"]

        result = _get_existing_subnets("vpc-12345")

        assert [str(network) for network in result] == ["10.1.2.0/24", "10.1.3.0/28"]

    def test_an_unparseable_entry_fails_closed(self, mock_network_inventory):
        """An observation that silently lost an entry is worse than none at all.

        The result becomes the occupied set the coordination routine reconciles
        drift against, so a dropped subnet reads as free capacity.
        """
        from cloud.exceptions import CloudNetworkInventoryError

        mock_network_inventory.list_subnet_cidrs.return_value = ["invalid-cidr", "10.1.2.0/24"]

        with pytest.raises(CloudNetworkInventoryError):
            _get_existing_subnets("vpc-12345")

    def test_does_not_leak_the_offending_value(self, mock_network_inventory):
        """Provider output does not belong in an error the caller may surface."""
        from cloud.exceptions import CloudNetworkInventoryError

        mock_network_inventory.list_subnet_cidrs.return_value = ["super-secret-garbage"]

        with pytest.raises(CloudNetworkInventoryError) as exc:
            _get_existing_subnets("vpc-12345")

        assert "super-secret-garbage" not in str(exc.value)

    def test_ignores_non_ipv4_networks(self, mock_network_inventory):
        mock_network_inventory.list_subnet_cidrs.return_value = ["2001:db8::/32", "10.1.2.0/24"]

        result = _get_existing_subnets("vpc-12345")

        assert [str(network) for network in result] == ["10.1.2.0/24"]

    def test_inventory_error_propagates(self, mock_network_inventory):
        """Cloud inventory errors propagate rather than becoming an empty observation.

        An empty observation is indistinguishable from "the network has no
        subnets", which would let the allocator hand out occupied CIDRs.
        """
        mock_network_inventory.list_subnet_cidrs.side_effect = RuntimeError("network lookup failed")

        with pytest.raises(RuntimeError, match="network lookup failed"):
            _get_existing_subnets("vpc-invalid")


class TestDBConnectionSeam:
    """The package reaches the database through the canonical factory only."""

    @patch.dict(
        "os.environ",
        {
            "DB_HOST": "db.internal",
            "DB_PORT": "5432",
            "DB_USER": "shifter",
            "DB_NAME": "shifter",
            "DB_PASSWORD": "local-dev",
        },
        clear=True,
    )
    def test_uses_the_canonical_factory_rather_than_a_second_one(self):
        """No second connection factory: one place owns the deployed auth posture.

        Driving it through the real factory to the ``psycopg`` boundary is what
        makes this meaningful -- asserting a delegation call would still pass if
        the factory stopped honouring the deployed auth mode.
        """
        sentinel = MagicMock()

        with patch("psycopg.connect", return_value=sentinel) as connect:
            assert _get_db_connection() is sentinel

        assert connect.call_args.kwargs["host"] == "db.internal"
        assert connect.call_args.kwargs["password"] == "local-dev"

    @patch.dict(
        "os.environ",
        {
            "CLOUD_PROVIDER": "gcp",
            "CLOUD_REGION": "us-central1",
            "DB_HOST": "db.internal",
            "DB_PORT": "5432",
            "DB_USER": "shifter",
            "DB_NAME": "shifter",
        },
        clear=True,
    )
    def test_cloud_db_auth_does_not_require_aws_region(self):
        """Cloud DB auth works on the adapter seam without an AWS-specific region.

        Carried over from the connection factory this package used to duplicate:
        GCP deployments set CLOUD_REGION and never AWS_REGION, so requiring the
        AWS spelling would break subnet reservation there.
        """
        import provisioner_db

        mock_auth = MagicMock()
        mock_auth.generate_auth_token.return_value = "gcp-auth-token"

        with (
            patch("cloud.get_db_auth", return_value=mock_auth),
            patch("psycopg.connect", return_value=MagicMock()) as mock_connect,
        ):
            provisioner_db.get_db_connection()

        mock_auth.generate_auth_token.assert_called_once_with(
            hostname="db.internal",
            port=5432,
            username="shifter",
        )
        assert mock_connect.call_args.kwargs["sslmode"] == "require"
