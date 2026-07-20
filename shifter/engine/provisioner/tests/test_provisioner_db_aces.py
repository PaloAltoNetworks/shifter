"""Tests for the ACES-native provisioner_db readers (ADR-032).

Drives get_aces_range_data_by_request_id (serialized plan, no cyberscript unwrap)
and get_aces_image_candidates (image registry read) with the DB connection mocked
at the boundary, asserting the row-to-dict mapping and that no cyberscript
persisted-envelope unwrap happens on the ACES path.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


_UNSET = object()


def _mock_conn(fetchone=_UNSET, fetchall=_UNSET):
    cursor = MagicMock()
    if fetchone is not _UNSET:
        cursor.fetchone.return_value = fetchone
    if fetchall is not _UNSET:
        cursor.fetchall.return_value = fetchall
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cursor


_PLAN = {"kind": "aces_provisioning_plan", "aces_sdl_version": "0.19.1", "resources": {"node.a": {}}}
# columns: request_id, range_id, user_id, range_config(plan), subnet_index, status,
# range_backend, instantiation_purpose (#1666 ownership binding)
_ACES_RANGE_ROW = ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", 42, 7, _PLAN, 5, "provisioning", "gce", "live_fire")


class TestGetAcesRangeData:
    def test_returns_serialized_plan_verbatim(self, monkeypatch):
        from provisioner_db_aces import get_aces_range_data_by_request_id

        conn, _cur = _mock_conn(fetchone=_ACES_RANGE_ROW)
        monkeypatch.setattr("provisioner_db_aces.get_db_connection", MagicMock(return_value=conn))

        result = get_aces_range_data_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert result["range_id"] == 42
        assert result["user_id"] == 7
        assert result["plan"] == _PLAN  # verbatim, no cyberscript unwrap
        assert result["status"] == "provisioning"

    def test_raises_when_not_found(self, monkeypatch):
        from provisioner_db_aces import get_aces_range_data_by_request_id

        conn, _cur = _mock_conn(fetchone=None)
        monkeypatch.setattr("provisioner_db_aces.get_db_connection", MagicMock(return_value=conn))

        try:
            get_aces_range_data_by_request_id("missing")
        except ValueError:
            return
        raise AssertionError("expected ValueError for missing range request")


class TestGetAcesContentDeliveryBindings:
    def test_maps_rows_to_binding_dicts(self, monkeypatch):
        from provisioner_db_aces import get_aces_content_delivery_bindings_by_request_id

        rows = [
            ("provision.node.attacker#file", "a" * 64, f"aces-content/aa/{'a' * 64}", 1024, 1),
            ("provision.node.victim#file", "b" * 64, f"aces-content/bb/{'b' * 64}", 2048, 1),
        ]
        conn, cursor = _mock_conn(fetchall=rows)
        monkeypatch.setattr("provisioner_db_aces.get_db_connection", MagicMock(return_value=conn))

        bindings = get_aces_content_delivery_bindings_by_request_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert bindings[0] == {
            "content_address": "provision.node.attacker#file",
            "sha256": "a" * 64,
            "storage_key": f"aces-content/aa/{'a' * 64}",
            "byte_count": 1024,
            "binding_version": 1,
        }
        assert bindings[1]["content_address"] == "provision.node.victim#file"
        sql = cursor.execute.call_args[0][0]
        assert "engine_aces_content_delivery_binding" in sql
        assert cursor.execute.call_args[0][1] == ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",)

    def test_returns_empty_list_when_no_bindings(self, monkeypatch):
        from provisioner_db_aces import get_aces_content_delivery_bindings_by_request_id

        conn, _cur = _mock_conn(fetchall=[])
        monkeypatch.setattr("provisioner_db_aces.get_db_connection", MagicMock(return_value=conn))

        assert get_aces_content_delivery_bindings_by_request_id("missing") == []


class TestGetAcesImageCandidates:
    def test_maps_rows_to_candidate_dicts(self, monkeypatch):
        from provisioner_db_aces import get_aces_image_candidates

        rows = [
            ("2024.1", "projects/x/global/images/kali-1", "e2-medium", 40, "pd-ssd"),
            ("", "projects/x/global/images/kali-latest", "", None, ""),
        ]
        conn, cursor = _mock_conn(fetchall=rows)
        monkeypatch.setattr("provisioner_db_aces.get_db_connection", MagicMock(return_value=conn))

        candidates = get_aces_image_candidates("gce", "kali")
        assert candidates[0] == {
            "source_version": "2024.1",
            "image_ref": "projects/x/global/images/kali-1",
            "machine_type": "e2-medium",
            "disk_size_gb": 40,
            "disk_type": "pd-ssd",
        }
        assert candidates[1]["source_version"] == ""
        # Query is filtered to enabled rows for the (provider, source_name).
        sql = cursor.execute.call_args[0][0]
        assert "enabled = TRUE" in sql
        assert cursor.execute.call_args[0][1] == ("gce", "kali")
