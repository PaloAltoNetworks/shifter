"""Tests for get_range_data_by_request_id NGFW instance lookup."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

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


# Range query columns: request_id, range_id, user_id, range_config, subnet_index,
# status, range_backend, instantiation_purpose (#1666 ownership binding),
# remote_access_capability (#1695 trusted OpenVPN activation contract),
# vpn_gateway_pool_slot (ADR-008-R7 gateway SA pool), placement_zone (#2029
# realized multi-region range-cell placement).
_RANGE_ROW_WITH_NGFW = (
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",  # request_id
    201,  # range_id
    1,  # user_id
    {"ngfw": True, "subnets": []},  # range_config
    5,  # subnet_index
    "provisioning",  # status
    None,  # range_backend (legacy/non-GCP)
    None,  # instantiation_purpose
    None,  # remote_access_capability
    None,  # vpn_gateway_pool_slot
    "status-quo",  # egress_mode (PLAT-238)
    "",  # placement_zone (single-zone / pre-#2029)
)

_RANGE_ROW_NO_NGFW = (
    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    201,
    1,
    {"subnets": []},  # ngfw not set
    5,
    "provisioning",
    None,  # range_backend
    None,  # instantiation_purpose
    None,  # remote_access_capability
    None,  # vpn_gateway_pool_slot
    "status-quo",  # egress_mode (PLAT-238)
    "",  # placement_zone
)


class TestGetRangeDataNGFWLookup:
    """NGFW instance ID lookup in get_range_data_by_request_id."""

    def test_finds_ngfw_using_provider_neutral_attachment_state(self, monkeypatch):
        """NGFW with attachable routing state should be linked to the range."""
        from provisioner_db import get_range_data_by_request_id

        ngfw_state = {
            "management_ip": "10.1.5.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            "data_eni_id": "eni-123",
        }
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] == 597

    def test_finds_ngfw_in_paused_state(self, monkeypatch):
        """NGFW in 'paused' state should still be found.

        When an NGFW is paused, subsequent range operations
        need its instance ID to manage resume/cascade correctly.
        """
        from provisioner_db import get_range_data_by_request_id

        ngfw_state = {
            "management_ip": "10.1.5.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            "data_eni_id": "eni-123",
        }
        mock_conn, mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        # Verify the NGFW lookup queries paused/pausing statuses. They are now bound
        # as DB-API parameters (enum-derived via ResourceStatus) rather than inlined.
        ngfw_call = mock_cursor.execute.call_args_list[1]
        sql_executed = ngfw_call[0][0]
        params = ngfw_call[0][1]
        assert "status in (%s, %s, %s, %s)" in sql_executed.lower()
        assert "paused" in params
        assert "pausing" in params
        assert result["ngfw_instance_id"] == 597

    def test_ngfw_query_does_not_require_aws_only_fields(self, monkeypatch):
        """NGFW lookup should not hardcode data_eni_id or service_name in SQL."""
        from provisioner_db import get_range_data_by_request_id

        ngfw_state = {
            "cloud_provider": "gcp",
            "management_ip": "10.200.0.10",
            "ssh_key_secret_id": "projects/test/secrets/ngfw-admin",
            "route_next_hop_ip": "10.200.0.2",
        }
        mock_conn, mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        # The second execute call is the NGFW lookup
        sql_executed = mock_cursor.execute.call_args_list[1][0][0]
        assert "service_name" not in sql_executed
        assert "data_eni_id" not in sql_executed
        assert result["ngfw_instance_id"] == 597

    def test_gcp_ngfw_route_next_hop_state_is_attachable(self, monkeypatch):
        """GCP/GDC NGFW route-next-hop state should count as attachable."""
        from provisioner_db import get_range_data_by_request_id

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

        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] == 812

    def test_no_ngfw_when_config_disabled(self, monkeypatch):
        """ngfw_instance_id should be None when ngfw not in range_config."""
        from provisioner_db import get_range_data_by_request_id

        # Only one fetchone call needed (no NGFW lookup)
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = _RANGE_ROW_NO_NGFW

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] is None

    def test_ngfw_not_found_returns_none(self, monkeypatch):
        """ngfw_instance_id should be None when no matching NGFW exists."""
        from provisioner_db import get_range_data_by_request_id

        # NGFW lookup returns None (no match)
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, None)

        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] is None

    def test_ngfw_without_attachment_state_returns_none(self, monkeypatch):
        """NGFW without routable attachment state should not be linked."""
        from provisioner_db import get_range_data_by_request_id

        ngfw_state = {
            "management_ip": "10.1.5.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_conn, _mock_cursor = _make_mock_cursor(_RANGE_ROW_WITH_NGFW, (597, ngfw_state))

        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["ngfw_instance_id"] is None

    def test_preserves_wrapped_scenario_envelope_for_range_cell_validation(self, monkeypatch):
        """The provisioner keeps the producer envelope as well as its payload view."""
        from shared.range_cells import build_scenario_artifact

        from provisioner_db import get_range_data_by_request_id

        envelope = build_scenario_artifact(
            {
                "spec_schema": "range_spec",
                "spec_version": "1",
                "payload": {"scenario_id": "scenario-a", "user_id": 7, "subnets": []},
            }
        )
        row = (*_RANGE_ROW_NO_NGFW[:3], envelope, *_RANGE_ROW_NO_NGFW[4:])
        mock_conn, _mock_cursor = _make_mock_cursor(row)
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))

        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["spec"] == envelope["payload"]
        assert result["spec_envelope"] == envelope

    def test_preserves_remote_access_capability(self, monkeypatch):
        """The provisioner receives the server-owned OpenVPN capability unchanged."""
        from provisioner_db import get_range_data_by_request_id

        capability = {
            "version": "openvpn-capability-v1",
            "channel": "openvpn",
            "target_ref": "11111111-2222-3333-4444-555555555555",
            "teardown_at": "2026-07-20T12:00:00Z",
        }
        # Override remote_access_capability (index 8), preserving the trailing
        # vpn_gateway_pool_slot (index 9), egress_mode (index 10), and
        # placement_zone (index 11) columns.
        row = (*_RANGE_ROW_NO_NGFW[:8], capability, *_RANGE_ROW_NO_NGFW[9:])
        mock_conn, _mock_cursor = _make_mock_cursor(row)
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))

        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["remote_access_capability"] == capability

    def test_preserves_placement_zone(self, monkeypatch):
        """The realized multi-region placement zone (#2029) reaches the provisioner
        unchanged. Guards the trailing-column (row[11]) mapping: an off-by-one
        against egress_mode would silently mis-place/mis-destroy ranges."""
        from provisioner_db import get_range_data_by_request_id

        # Override placement_zone (index 11) with a non-default value.
        row = (*_RANGE_ROW_NO_NGFW[:11], "us-east4-a")
        mock_conn, _mock_cursor = _make_mock_cursor(row)
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))

        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["placement_zone"] == "us-east4-a"


class TestGetRangeDataEgressMode:
    """The pinned range egress mode is read from the range row (PLAT-238)."""

    def test_reads_the_pinned_egress_mode_from_the_row(self, monkeypatch):
        from provisioner_db import get_range_data_by_request_id

        # Override egress_mode (index 10) to a non-default value and prove it is
        # surfaced; a mis-indexed or dropped column would leave this default.
        row = (*_RANGE_ROW_NO_NGFW[:10], "none", _RANGE_ROW_NO_NGFW[11])
        mock_conn, _mock_cursor = _make_mock_cursor(row)
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))

        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["egress_mode"] == "none"

    def test_null_egress_mode_falls_back_to_status_quo(self, monkeypatch):
        from provisioner_db import get_range_data_by_request_id

        row = (*_RANGE_ROW_NO_NGFW[:10], None, _RANGE_ROW_NO_NGFW[11])
        mock_conn, _mock_cursor = _make_mock_cursor(row)
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))

        result = get_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert result["egress_mode"] == "status-quo"
