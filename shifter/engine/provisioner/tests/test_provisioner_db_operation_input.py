"""Tests for the operation-input projection reader (ADR-043 phase 5, #1837).

Drives ``provisioner_db_operation_input``: the provisioner selects the *exact*
immutable input row for its canonical ``operation_id`` and validates the
envelope before any cloud or guest mutation. It never reads "latest by
request", and it never falls back to a domain-table read.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_UNSET = object()

_OPERATION_ID = "11111111-2222-3333-4444-555555555555"
_REQUEST_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_SHA = "c" * 64


def _mock_conn(fetchone=_UNSET):
    cursor = MagicMock()
    if fetchone is not _UNSET:
        cursor.fetchone.return_value = fetchone
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def _payload(**overrides):
    payload = {
        "plan": {"kind": "raes_provisioning_plan", "resources": {}},
        "delivery_bindings": [
            {
                "content_address": "content.c",
                "sha256": _SHA,
                "storage_key": f"raes/content-delivery/cc/{_SHA}",
                "byte_count": 4,
                "binding_version": 1,
            }
        ],
        "access_bindings": [],
        "artifact_bindings": [],
        "image_candidates": {
            "gce:kali": [
                {
                    "source_version": "",
                    "image_ref": "projects/p/global/images/kali",
                    "machine_type": "",
                    "disk_size_gb": None,
                    "disk_type": "",
                }
            ]
        },
        "range_backend": "gce",
        "instantiation_purpose": "training",
        "legacy_range_id": 42,
    }
    payload.update(overrides)
    return payload


def _envelope(**overrides):
    envelope = {
        "contract_version": "1",
        "operation_id": _OPERATION_ID,
        "request_id": _REQUEST_ID,
        "resource": "raes-range",
        "operation": "provision",
        "payload": _payload(),
    }
    envelope.update(overrides)
    return envelope


def _row(envelope=None, **column_overrides):
    """Columns: operation_id, request_id, resource, operation, contract_version, envelope."""
    columns = {
        "operation_id": _OPERATION_ID,
        "request_id": _REQUEST_ID,
        "resource": "raes-range",
        "operation": "provision",
        "contract_version": "1",
    }
    columns.update(column_overrides)
    return (*columns.values(), envelope if envelope is not None else _envelope())


def _read(monkeypatch, row, **kwargs):
    import provisioner_db_operation_input as reader

    conn, cursor = _mock_conn(fetchone=row)
    monkeypatch.setattr(reader, "get_db_connection", MagicMock(return_value=conn))
    call_kwargs = {
        "operation_id": _OPERATION_ID,
        "request_id": _REQUEST_ID,
        "resource": "raes-range",
        "operation": "provision",
    }
    call_kwargs.update(kwargs)
    return reader.get_operation_input(**call_kwargs), cursor


class TestExactRowSelection:
    def test_returns_the_validated_envelope_payload(self, monkeypatch):
        result, _cursor = _read(monkeypatch, _row())
        assert result.payload["legacy_range_id"] == 42
        assert result.request_id == _REQUEST_ID
        assert result.operation_id == _OPERATION_ID

    def test_selects_by_operation_id_never_latest_by_request(self, monkeypatch):
        # A retry must consume its own generation's input even after the
        # registry, bindings, or backend have changed for a newer one.
        _result, cursor = _read(monkeypatch, _row())
        sql, params = cursor.execute.call_args.args
        assert "operation_id = %s" in sql
        assert params == (_OPERATION_ID,)
        assert "ORDER BY" not in sql.upper()
        assert "LIMIT" not in sql.upper()

    def test_a_missing_input_row_fails_closed(self, monkeypatch):
        import provisioner_db_operation_input as reader

        with pytest.raises(reader.OperationInputError):
            _read(monkeypatch, None)


class TestDiscriminatorsAreChecked:
    def test_a_row_for_another_resource_is_refused(self, monkeypatch):
        import provisioner_db_operation_input as reader

        row = _row(_envelope(resource="range"), resource="range")
        with pytest.raises(reader.OperationInputError):
            _read(monkeypatch, row)

    def test_a_row_for_another_operation_is_refused(self, monkeypatch):
        import provisioner_db_operation_input as reader

        row = _row(_envelope(operation="destroy"), operation="destroy")
        with pytest.raises(reader.OperationInputError):
            _read(monkeypatch, row)

    def test_a_column_disagreeing_with_the_envelope_is_refused(self, monkeypatch):
        # The flattened columns are what the query selected on; a row whose
        # columns disagree with the signed-shape envelope would be consumed
        # under the wrong identity.
        import provisioner_db_operation_input as reader

        row = _row(_envelope(request_id="99999999-9999-9999-9999-999999999999"))
        with pytest.raises(reader.OperationInputError):
            _read(monkeypatch, row)

    def test_an_unsupported_contract_version_is_refused(self, monkeypatch):
        import provisioner_db_operation_input as reader

        row = _row(_envelope(contract_version="99"), contract_version="99")
        with pytest.raises(reader.OperationInputError):
            _read(monkeypatch, row)

    def test_a_malformed_envelope_is_refused(self, monkeypatch):
        import provisioner_db_operation_input as reader

        row = _row({"not": "an envelope"})
        with pytest.raises(reader.OperationInputError):
            _read(monkeypatch, row)


class TestRaesProjection:
    def test_parses_into_the_closed_raes_projection(self, monkeypatch):
        import provisioner_db_operation_input as reader

        conn, _cursor = _mock_conn(fetchone=_row())
        monkeypatch.setattr(reader, "get_db_connection", MagicMock(return_value=conn))
        run = reader.get_raes_operation_input(_OPERATION_ID, request_id=_REQUEST_ID, operation="provision")
        projection = run.input
        assert projection.legacy_range_id == 42
        assert projection.range_backend == "gce"
        assert [b.content_address for b in projection.delivery_bindings] == ["content.c"]
        assert projection.image_candidates_for("gce", "kali")[0]["image_ref"] == "projects/p/global/images/kali"

    def test_a_tampered_binding_fails_before_any_cloud_work(self, monkeypatch):
        import provisioner_db_operation_input as reader

        payload = _payload()
        payload["delivery_bindings"][0]["storage_key"] = ""
        conn, _cursor = _mock_conn(fetchone=_row(_envelope(payload=payload)))
        monkeypatch.setattr(reader, "get_db_connection", MagicMock(return_value=conn))
        with pytest.raises(reader.OperationInputError):
            reader.get_raes_operation_input(_OPERATION_ID, request_id=_REQUEST_ID, operation="provision")


class TestRequestIdentityBinding:
    """The generation identity is compound: (operation_id, request_id).

    Selecting on operation_id alone lets a caller that can influence command
    argv pair one request's operation with another request's id. The row's own
    flattened columns agree with its own envelope in that case, so
    self-consistency is not the check -- binding to the command is.
    """

    def test_a_mismatched_command_request_is_refused(self, monkeypatch):
        import provisioner_db_operation_input as reader

        row = _row()
        with pytest.raises(reader.OperationInputError):
            _read(monkeypatch, row, request_id="99999999-9999-9999-9999-999999999999")

    def test_the_raes_consumer_refuses_a_mismatched_request(self, monkeypatch):
        import provisioner_db_operation_input as reader

        conn, _cursor = _mock_conn(fetchone=_row())
        monkeypatch.setattr(reader, "get_db_connection", MagicMock(return_value=conn))
        with pytest.raises(reader.OperationInputError):
            reader.get_raes_operation_input(
                _OPERATION_ID, request_id="99999999-9999-9999-9999-999999999999", operation="provision"
            )

    def test_the_validated_identity_is_returned_for_callers_to_build_refs_from(self, monkeypatch):
        # Callers must correlate results from the identity the row proved, not
        # from the argv they were handed.
        import provisioner_db_operation_input as reader

        conn, _cursor = _mock_conn(fetchone=_row())
        monkeypatch.setattr(reader, "get_db_connection", MagicMock(return_value=conn))
        run = reader.get_raes_operation_input(_OPERATION_ID, request_id=_REQUEST_ID, operation="provision")
        assert (run.operation_id, run.request_id) == (_OPERATION_ID, _REQUEST_ID)
