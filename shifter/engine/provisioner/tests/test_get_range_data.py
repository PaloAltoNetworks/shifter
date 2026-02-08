"""Tests for get_range_data_by_request_id NGFW instance lookup.

The NGFW lookup query must find the user's active NGFW instance
and return its ID so the range can be linked to the NGFW for
pause/resume/destroy cascade operations.
"""

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

    def test_finds_ngfw_without_service_name(self):
        """NGFW with data_eni_id but no service_name should be found.

        This is the bug: the query filtered on service_name IS NOT NULL,
        but service_name is never populated. The lookup should not require
        service_name.
        """
        from main import get_range_data_by_request_id

        # NGFW lookup returns instance id=597
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597,))

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] == 597

    def test_finds_ngfw_in_stopped_state(self):
        """NGFW in 'stopped' state should still be found.

        When an NGFW is paused (stopped), subsequent range operations
        need its instance ID to manage resume/cascade correctly.
        """
        from main import get_range_data_by_request_id

        mock_conn, mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597,))

        with patch("main.get_db_connection", return_value=mock_conn):
            result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        # Verify the SQL includes stopped/stopping statuses
        sql_executed = mock_cursor.execute.call_args_list[1][0][0]
        assert "stopped" in sql_executed.lower()
        assert result["ngfw_instance_id"] == 597

    def test_ngfw_query_checks_data_eni_not_service_name(self):
        """NGFW lookup should filter on data_eni_id, not service_name.

        data_eni_id is populated during NGFW provisioning and confirms
        the NGFW has real infrastructure. service_name is never set.
        """
        from main import get_range_data_by_request_id

        mock_conn, mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597,))

        with patch("main.get_db_connection", return_value=mock_conn):
            get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        # The second execute call is the NGFW lookup
        sql_executed = mock_cursor.execute.call_args_list[1][0][0]
        assert "service_name" not in sql_executed
        assert "data_eni_id" in sql_executed

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
