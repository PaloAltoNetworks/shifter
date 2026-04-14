"""Tests for get_range_data_by_request_id NGFW instance lookup."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_mock_cursor(range_row, ngfw_row=None):
    """Build a mock cursor that returns range_row first, then ngfw_row.

    Args:
        range_row: Tuple returned by the range query (fetchone call 1).
        ngfw_row: Tuple returned by the NGFW lookup (fetchone call 2), or None.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [range_row, ngfw_row]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    return mock_conn, mock_cursor


# Range query columns: request_id, range_id, user_id, range_config, subnet_index, status
_RANGE_ROW_WITH_NGFW = (
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",  # request_id
    201,  # range_id
    1,  # user_id
    {"ngfw": True, "subnets": []},  # range_config
    5,  # subnet_index
    "provisioning",  # status
)

_RANGE_ROW_NO_NGFW = (
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    201,
    1,
    {"subnets": []},  # ngfw not set
    5,
    "provisioning",
)


class TestGetRangeDataNGFWLookup:
    """NGFW instance ID lookup in get_range_data_by_request_id."""

    def test_finds_ngfw_using_provider_neutral_attachment_state(self):
        """NGFW with attachable routing state should be linked to the range."""
        from main import get_range_data_by_request_id

        ngfw_state = {
            "management_ip": "10.1.5.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            "data_eni_id": "eni-123",
        }
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] == 597

    def test_finds_ngfw_in_paused_state(self):
        """NGFW in 'paused' state should still be found.

        When an NGFW is paused, subsequent range operations
        need its instance ID to manage resume/cascade correctly.
        """
        from main import get_range_data_by_request_id

        ngfw_state = {
            "management_ip": "10.1.5.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            "data_eni_id": "eni-123",
        }
        mock_conn, mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        # Verify the SQL includes paused/pausing statuses
        sql_executed = mock_cursor.execute.call_args_list[1][0][0]
        assert "paused" in sql_executed.lower()
        assert result["ngfw_instance_id"] == 597

    def test_ngfw_query_does_not_require_aws_only_fields(self):
        """NGFW lookup should not hardcode data_eni_id or service_name in SQL."""
        from main import get_range_data_by_request_id

        ngfw_state = {
            "cloud_provider": "gcp",
            "management_ip": "10.200.0.10",
            "ssh_key_secret_id": "projects/test/secrets/ngfw-admin",
            "route_next_hop_ip": "10.200.0.2",
        }
        mock_conn, mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        with patch("main.get_db_connection", return_value=mock_conn):
            get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        # The second execute call is the NGFW lookup
        sql_executed = mock_cursor.execute.call_args_list[1][0][0]
        assert "service_name" not in sql_executed
        assert "data_eni_id" not in sql_executed

    def test_gcp_ngfw_route_next_hop_state_is_attachable(self):
        """GCP/GDC NGFW route-next-hop state should count as attachable."""
        from main import get_range_data_by_request_id

        ngfw_state = {
            "cloud_provider": "gcp",
            "management_ip": "10.200.0.10",
            "ssh_key_secret_id": "projects/test/secrets/ngfw-admin",
            "route_next_hop_ip": "10.200.0.2",
            "provider_metadata": {
                "gcp": {
                    "attachment_mode": "gdc-static-route",
                }
            },
        }
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (812, ngfw_state))

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] == 812

    def test_no_ngfw_when_config_disabled(self):
        """ngfw_instance_id should be None when ngfw not in range_config."""
        from main import get_range_data_by_request_id

        # Only one fetchone call needed (no NGFW lookup)
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = _RANGE_ROW_NO_NGFW

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] is None

    def test_ngfw_not_found_returns_none(self):
        """ngfw_instance_id should be None when no matching NGFW exists."""
        from main import get_range_data_by_request_id

        # NGFW lookup returns None (no match)
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, None)

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] is None

    def test_ngfw_without_attachment_state_returns_none(self):
        """NGFW without routable attachment state should not be linked."""
        from main import get_range_data_by_request_id

        ngfw_state = {
            "management_ip": "10.1.5.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] is None
