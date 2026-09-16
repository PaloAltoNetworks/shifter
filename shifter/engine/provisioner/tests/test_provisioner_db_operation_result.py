"""Tests for the provisioner operation-result inbox append path (ADR-043, #1834).

Phase 7 (#1839) removed the range-event outbox suite; these tests cover the
operation boundary the phase deliberately leaves intact.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock


def _make_conn_mock():
    """Return (conn_mock, cursor_mock) with proper context-manager protocol."""
    cursor_mock = MagicMock()
    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    conn_mock.cursor.return_value.__enter__ = MagicMock(return_value=cursor_mock)
    conn_mock.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn_mock, cursor_mock


class TestAppendOperationResult:
    """Unit tests for provisioner_db.append_operation_result (ADR-043 Phase 2, #1834)."""

    OPERATION_ID = "11111111-1111-1111-1111-111111111111"
    REQUEST_ID = "22222222-2222-2222-2222-222222222222"

    def test_own_transaction_path_opens_connection_and_commits(self, monkeypatch):
        """Without a cursor arg, opens its own connection and commits."""
        conn_mock, cursor_mock = _make_conn_mock()
        cursor_mock.rowcount = 1
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        from provisioner_db_appends import append_operation_result

        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="provision",
            result_kind="TERMINAL_SUCCESS",
            result_payload={"status": "ready"},
        )

        cursor_mock.execute.assert_called_once()
        conn_mock.commit.assert_called_once()

    def test_insert_sets_every_non_defaulted_column_including_pending_disposition(self, monkeypatch):
        """The raw INSERT sets every column the model defaults ORM-side, not DB-side."""
        conn_mock, cursor_mock = _make_conn_mock()
        cursor_mock.rowcount = 1
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        from shared.operation_envelope import build_operation_envelope, canonical_payload_digest

        from provisioner_db_appends import append_operation_result

        payload = {"status": "ready", "range_id": 42}
        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="provision",
            result_kind="TERMINAL_SUCCESS",
            result_payload=payload,
        )

        sql_arg, params = cursor_mock.execute.call_args[0]
        sql_upper = sql_arg.upper()
        for column in (
            "OPERATION_ID",
            "REQUEST_ID",
            "RESOURCE",
            "OPERATION",
            "CONTRACT_VERSION",
            "RESULT_KIND",
            "RESULT_STEP",
            "RESULT_IDENTITY",
            "PAYLOAD_DIGEST",
            "ENVELOPE",
            "DISPOSITION",
            "DISPOSITION_DETAIL",
            "CREATED_AT",
        ):
            assert column in sql_upper
        assert "ON CONFLICT" in sql_upper
        assert "DO NOTHING" in sql_upper
        assert "'PENDING'" in sql_arg
        assert "NOW()" in sql_upper

        expected_envelope = build_operation_envelope(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="provision",
            payload=payload,
        )
        expected_digest = canonical_payload_digest(payload)
        assert params == (
            self.OPERATION_ID,
            self.REQUEST_ID,
            "range",
            "provision",
            "1",
            "TERMINAL_SUCCESS",
            "",
            f"{self.OPERATION_ID}:TERMINAL_SUCCESS",
            expected_digest,
            json.dumps(expected_envelope),
        )

    def test_result_identity_is_deterministic_per_operation_and_kind(self, monkeypatch):
        """result_identity is f'{operation_id}:{result_kind}', not payload-derived."""
        conn_mock, cursor_mock = _make_conn_mock()
        cursor_mock.rowcount = 1
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        from provisioner_db_appends import append_operation_result

        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="ngfw",
            operation="start",
            result_kind="RESOURCE_STATE",
            result_payload={"status": "ready"},
        )

        params = cursor_mock.execute.call_args[0][1]
        assert params[7] == f"{self.OPERATION_ID}:RESOURCE_STATE"

    def test_caller_cursor_path_skips_own_connection_and_uses_savepoint(self, monkeypatch):
        """When cur is provided, no new connection opens and the append rides a SAVEPOINT."""
        mock_get_conn = MagicMock()
        monkeypatch.setattr("provisioner_db.get_db_connection", mock_get_conn)

        from provisioner_db_appends import append_operation_result

        caller_cursor = MagicMock()
        caller_cursor.rowcount = 1

        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="destroy",
            result_kind="TERMINAL_SUCCESS",
            result_payload={"status": "destroyed"},
            cur=caller_cursor,
        )

        mock_get_conn.assert_not_called()
        caller_cursor.execute.assert_called_once()
        caller_cursor.connection.transaction.assert_called_once()

    def test_caller_cursor_path_does_not_commit(self, monkeypatch):
        """When cur is provided, commit is owned by the caller."""
        mock_get_conn = MagicMock()
        monkeypatch.setattr("provisioner_db.get_db_connection", mock_get_conn)

        from provisioner_db_appends import append_operation_result

        caller_cursor = MagicMock()
        caller_cursor.rowcount = 1

        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="destroy",
            result_kind="TERMINAL_SUCCESS",
            result_payload={"status": "destroyed"},
            cur=caller_cursor,
        )

        mock_get_conn.assert_not_called()

    def test_replay_with_identical_digest_is_a_harmless_no_op(self, monkeypatch):
        """Same result_identity + same payload digest: no warning, no raise."""
        from provisioner_db_appends import append_operation_result

        caller_cursor = MagicMock()
        caller_cursor.rowcount = 0
        mock_warning = MagicMock()
        monkeypatch.setattr("provisioner_db_appends.logger.warning", mock_warning)

        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="provision",
            result_kind="TERMINAL_SUCCESS",
            result_payload={"status": "ready"},
            cur=caller_cursor,
        )

        mock_warning.assert_not_called()
        assert caller_cursor.execute.call_count == 1

    def test_append_never_reads_the_inbox_back(self, monkeypatch):
        """The provisioner holds INSERT only on the inbox (engine migration 0036)."""
        from provisioner_db_appends import append_operation_result

        caller_cursor = MagicMock()
        caller_cursor.rowcount = 0

        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="provision",
            result_kind="TERMINAL_SUCCESS",
            result_payload={"status": "ready"},
            cur=caller_cursor,
        )

        for call in caller_cursor.execute.call_args_list:
            assert "SELECT" not in call[0][0].upper()
        caller_cursor.fetchone.assert_not_called()

    def test_conflicting_payload_gets_a_distinct_identity_on_the_authoritative_path(self, monkeypatch):
        """Two different payloads for one step must not collapse onto one identity."""
        from shared.operation_results import ResultStep

        from provisioner_db_appends import OperationRef, append_operation_step_result

        identities = []
        for uuid in ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"):
            caller_cursor = MagicMock()
            append_operation_step_result(
                OperationRef(request_id=self.REQUEST_ID, operation_id=self.OPERATION_ID),
                resource="range",
                operation="pause",
                step=ResultStep.RANGE_INSTANCES_PAUSED,
                result_payload={"instances": [{"instance_uuid": uuid, "status": "paused"}]},
                cur=caller_cursor,
            )
            identities.append(caller_cursor.execute.call_args[0][1][7])

        assert identities[0] != identities[1]

    def test_unexpected_error_is_logged_and_swallowed_not_raised(self, monkeypatch):
        """A shadow-append failure must never fail an authoritative provisioning operation."""
        from provisioner_db_appends import append_operation_result

        caller_cursor = MagicMock()
        caller_cursor.execute.side_effect = RuntimeError("boom")
        mock_warning = MagicMock()
        monkeypatch.setattr("provisioner_db_appends.logger.warning", mock_warning)

        append_operation_result(
            operation_id=self.OPERATION_ID,
            request_id=self.REQUEST_ID,
            resource="range",
            operation="provision",
            result_kind="TERMINAL_SUCCESS",
            result_payload={"status": "ready"},
            cur=caller_cursor,
        )

        mock_warning.assert_called_once()
        assert mock_warning.call_args[0][1] == "operation_result_inbox_append_failed"

    def test_invalid_envelope_input_is_swallowed_not_raised(self, monkeypatch):
        """An invalid operation_id/resource/operation fails envelope validation but never raises."""
        from provisioner_db_appends import append_operation_result

        mock_get_conn = MagicMock()
        monkeypatch.setattr("provisioner_db.get_db_connection", mock_get_conn)
        mock_warning = MagicMock()
        monkeypatch.setattr("provisioner_db_appends.logger.warning", mock_warning)

        append_operation_result(
            operation_id="not-a-uuid",
            request_id=self.REQUEST_ID,
            resource="range",
            operation="provision",
            result_kind="TERMINAL_SUCCESS",
            result_payload={"status": "ready"},
        )

        mock_warning.assert_called_once()
        mock_get_conn.assert_not_called()


class TestAppendOperationResultWiredIntoWriteProvisionedState:
    """write_provisioned_state issues the shadow append only when operation_id is present."""

    def _make_full_conn_mock(self):
        cursor_mock = MagicMock()
        cursor_mock.rowcount = 1
        conn_mock = MagicMock()
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=False)
        conn_mock.cursor.return_value.__enter__ = MagicMock(return_value=cursor_mock)
        conn_mock.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn_mock, cursor_mock

    def _patch_state_helpers(self, monkeypatch):
        monkeypatch.setattr("provisioner_db._get_cloud_provider", MagicMock(return_value="aws"))
        monkeypatch.setattr("provisioner_db._build_subnet_state", MagicMock(return_value={"cloud_provider": "aws"}))
        monkeypatch.setattr("provisioner_db._build_instance_state", MagicMock(return_value={"cloud_provider": "aws"}))
        monkeypatch.setattr("provisioner_db._build_provisioned_instance_payload", MagicMock(return_value={}))

    def test_appends_when_operation_id_present(self, monkeypatch):
        conn_mock, _cursor_mock = self._make_full_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))
        self._patch_state_helpers(monkeypatch)

        append_calls: list[dict] = []

        def _capture(*, cur=None, **kwargs):
            append_calls.append({"cur": cur, **kwargs})

        monkeypatch.setattr("provisioner_db_appends.append_operation_result", _capture)

        from provisioner_db import write_provisioned_state
        from provisioner_db_appends import OperationRef

        write_provisioned_state(
            range_id=42,
            subnets={"attack": {"uuid": "sub-uuid-1"}},
            instances=[{"uuid": "inst-uuid-1"}],
            operation=OperationRef(request_id="req-1", operation_id="op-1"),
        )

        assert len(append_calls) == 1
        assert append_calls[0]["operation_id"] == "op-1"
        assert append_calls[0]["request_id"] == "req-1"
        assert append_calls[0]["resource"] == "range"
        assert append_calls[0]["operation"] == "provision"
        assert append_calls[0]["result_kind"] == "TERMINAL_SUCCESS"
        assert append_calls[0]["cur"] is not None

    def test_skips_append_when_operation_id_is_none(self, monkeypatch):
        conn_mock, _cursor_mock = self._make_full_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))
        self._patch_state_helpers(monkeypatch)

        mock_append = MagicMock()
        monkeypatch.setattr("provisioner_db_appends.append_operation_result", mock_append)

        from provisioner_db import write_provisioned_state

        write_provisioned_state(
            range_id=42,
            subnets={"attack": {"uuid": "sub-uuid-1"}},
            instances=[{"uuid": "inst-uuid-1"}],
        )

        mock_append.assert_not_called()


class TestAppendOperationResultWiredIntoMarkRangeInstancesDestroyed:
    """mark_range_instances_destroyed issues the shadow append only when operation_id is present."""

    def _make_conn(self):
        cursor_mock = MagicMock()
        cursor_mock.rowcount = 1
        conn_mock = MagicMock()
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=False)
        conn_mock.cursor.return_value.__enter__ = MagicMock(return_value=cursor_mock)
        conn_mock.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn_mock, cursor_mock

    def test_appends_when_operation_id_present(self, monkeypatch):
        conn_mock, _cursor_mock = self._make_conn()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        mock_append = MagicMock()
        monkeypatch.setattr("provisioner_db_appends.append_operation_result", mock_append)

        from provisioner_db import mark_range_instances_destroyed
        from provisioner_db_appends import OperationRef

        mark_range_instances_destroyed(42, operation=OperationRef(request_id="req-1", operation_id="op-1"))

        mock_append.assert_called_once()
        _args, kwargs = mock_append.call_args
        assert kwargs["operation_id"] == "op-1"
        assert kwargs["request_id"] == "req-1"
        assert kwargs["resource"] == "range"
        assert kwargs["operation"] == "destroy"
        assert kwargs["result_kind"] == "TERMINAL_SUCCESS"
        assert kwargs["cur"] is not None

    def test_skips_append_when_operation_id_is_none(self, monkeypatch):
        conn_mock, _cursor_mock = self._make_conn()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        mock_append = MagicMock()
        monkeypatch.setattr("provisioner_db_appends.append_operation_result", mock_append)

        from provisioner_db import mark_range_instances_destroyed

        mark_range_instances_destroyed(42)

        mock_append.assert_not_called()
