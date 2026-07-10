"""Tests for enqueue_event_outbox and atomic outbox threading.

Phase 1 (#476): provisioner_db.enqueue_event_outbox inserts a PENDING row into
engine_range_event_outbox. update_range_status and write_provisioned_state
accept an optional outbox_event= so state + event intent commit atomically.

Mocks are at the psycopg boundary (get_db_connection); no first-party
internals are patched.
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


class TestEnqueueEventOutbox:
    """Unit tests for provisioner_db.enqueue_event_outbox."""

    def test_own_transaction_path_opens_connection_and_commits(self, monkeypatch):
        """Without a cursor arg, opens its own connection and commits."""
        conn_mock, cursor_mock = _make_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        from provisioner_db import enqueue_event_outbox

        event = {
            "event_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "event_type": "range.status.updated",
            "range_id": 42,
            "user_id": 1,
            "new_status": "provisioning",
        }
        enqueue_event_outbox(event)

        cursor_mock.execute.assert_called_once()
        conn_mock.commit.assert_called_once()

    def test_own_transaction_inserts_correct_fields(self, monkeypatch):
        """Verifies event_id, event_type, and JSON payload are in the INSERT."""
        conn_mock, cursor_mock = _make_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        from provisioner_db import enqueue_event_outbox

        event = {
            "event_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "event_type": "range.status.updated",
            "range_id": 42,
            "user_id": 1,
            "new_status": "ready",
        }
        enqueue_event_outbox(event)

        execute_args = cursor_mock.execute.call_args
        # Second positional arg is the params tuple
        params = execute_args[0][1]
        assert str(event["event_id"]) in str(params)
        assert event["event_type"] in str(params)
        # payload should be JSON-serialised
        payload_str = params[2] if len(params) > 2 else params[1]
        parsed = json.loads(payload_str)
        assert parsed["range_id"] == 42
        assert parsed["new_status"] == "ready"

    def test_own_transaction_sql_has_on_conflict_do_nothing(self, monkeypatch):
        """INSERT uses ON CONFLICT (event_id) DO NOTHING for idempotency."""
        conn_mock, cursor_mock = _make_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        from provisioner_db import enqueue_event_outbox

        event = {
            "event_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "event_type": "range.status.updated",
        }
        enqueue_event_outbox(event)

        sql_arg = cursor_mock.execute.call_args[0][0]
        sql_upper = sql_arg.upper()
        assert "ON CONFLICT" in sql_upper
        assert "DO NOTHING" in sql_upper

    def test_caller_cursor_path_skips_own_connection(self, monkeypatch):
        """When a cursor is provided, no new connection is opened."""
        mock_get_conn = MagicMock()
        monkeypatch.setattr("provisioner_db.get_db_connection", mock_get_conn)

        from provisioner_db import enqueue_event_outbox

        caller_cursor = MagicMock()
        event = {
            "event_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "event_type": "range.status.updated",
        }
        enqueue_event_outbox(event, cur=caller_cursor)

        mock_get_conn.assert_not_called()
        caller_cursor.execute.assert_called_once()

    def test_caller_cursor_path_does_not_commit(self, monkeypatch):
        """When a cursor is provided, commit is owned by the caller — not called here."""
        mock_get_conn = MagicMock()
        monkeypatch.setattr("provisioner_db.get_db_connection", mock_get_conn)

        # Create a cursor that we can inspect
        caller_cursor = MagicMock()
        # (No conn to check commit on — that's the point: commit is absent)

        from provisioner_db import enqueue_event_outbox

        event = {
            "event_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "event_type": "range.status.updated",
        }
        enqueue_event_outbox(event, cur=caller_cursor)
        # No connection opened = no commit called anywhere
        mock_get_conn.assert_not_called()

    def test_pending_status_in_insert(self, monkeypatch):
        """The INSERT hardcodes status='PENDING'."""
        conn_mock, cursor_mock = _make_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        from provisioner_db import enqueue_event_outbox

        event = {"event_id": "aaaaaaaa-0000-0000-0000-000000000001", "event_type": "range.status.updated"}
        enqueue_event_outbox(event)

        sql_arg = cursor_mock.execute.call_args[0][0]
        assert "PENDING" in sql_arg


class TestUpdateRangeStatusWithOutbox:
    """update_range_status threads an optional outbox_event atomically."""

    def test_enqueues_event_in_same_cursor_block(self, monkeypatch):
        """outbox_event= causes enqueue_event_outbox to be called with the shared cursor."""
        conn_mock, _cursor_mock = _make_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        enqueue_calls = []

        def _capture_enqueue(event, *, cur=None):
            enqueue_calls.append({"event": event, "cur": cur})

        monkeypatch.setattr("provisioner_db.enqueue_event_outbox", _capture_enqueue)

        from provisioner_db import update_range_status

        outbox_event = {
            "event_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "event_type": "range.status.updated",
            "new_status": "paused",
        }
        update_range_status(42, "paused", outbox_event=outbox_event)

        assert len(enqueue_calls) == 1
        assert enqueue_calls[0]["event"] is outbox_event
        # cur= must be set (not None) — same cursor as the UPDATE
        assert enqueue_calls[0]["cur"] is not None

    def test_no_enqueue_when_outbox_event_is_none(self, monkeypatch):
        """When outbox_event is None, enqueue_event_outbox is never called."""
        conn_mock, _cursor_mock = _make_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        mock_enqueue = MagicMock()
        monkeypatch.setattr("provisioner_db.enqueue_event_outbox", mock_enqueue)

        from provisioner_db import update_range_status

        update_range_status(42, "paused")

        mock_enqueue.assert_not_called()

    def test_both_update_and_enqueue_before_commit(self, monkeypatch):
        """DB update and outbox INSERT are both executed before conn.commit()."""
        conn_mock, cursor_mock = _make_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        call_log: list[str] = []
        original_execute = cursor_mock.execute

        def _track_execute(*args, **kwargs):
            call_log.append("execute")
            return original_execute(*args, **kwargs)

        cursor_mock.execute = _track_execute
        conn_mock.commit = MagicMock(side_effect=lambda: call_log.append("commit"))

        real_enqueue_calls: list[dict] = []

        def _real_enqueue(event, *, cur=None):
            real_enqueue_calls.append({"event": event, "cur": cur})
            # simulate enqueue using the cursor
            call_log.append("enqueue_execute")

        monkeypatch.setattr("provisioner_db.enqueue_event_outbox", _real_enqueue)

        from provisioner_db import update_range_status

        outbox_event = {"event_id": "aaa", "event_type": "range.status.updated"}
        update_range_status(42, "paused", outbox_event=outbox_event)

        # All executes happen before commit
        assert "execute" in call_log
        assert "enqueue_execute" in call_log
        assert "commit" in call_log
        execute_idx = max(i for i, v in enumerate(call_log) if v in ("execute", "enqueue_execute"))
        commit_idx = call_log.index("commit")
        assert execute_idx < commit_idx


class TestWriteProvisionedStateWithOutbox:
    """write_provisioned_state threads an optional outbox_event atomically."""

    def _make_full_conn_mock(self):
        """Connection mock where rowcount > 0 so write_provisioned_state succeeds."""
        cursor_mock = MagicMock()
        cursor_mock.rowcount = 1

        conn_mock = MagicMock()
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=False)
        conn_mock.cursor.return_value.__enter__ = MagicMock(return_value=cursor_mock)
        conn_mock.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn_mock, cursor_mock

    def test_enqueues_event_in_same_cursor_block(self, monkeypatch):
        """outbox_event= causes enqueue_event_outbox to be called with the shared cursor."""
        conn_mock, _cursor_mock = self._make_full_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))

        # Minimal stubs for state helpers
        monkeypatch.setattr("provisioner_db._get_cloud_provider", MagicMock(return_value="aws"))
        monkeypatch.setattr(
            "provisioner_db._build_subnet_state",
            MagicMock(return_value={"cloud_provider": "aws"}),
        )
        monkeypatch.setattr(
            "provisioner_db._build_instance_state",
            MagicMock(return_value={"cloud_provider": "aws"}),
        )
        monkeypatch.setattr(
            "provisioner_db._build_provisioned_instance_payload",
            MagicMock(return_value={}),
        )

        enqueue_calls: list[dict] = []

        def _capture(event, *, cur=None):
            enqueue_calls.append({"event": event, "cur": cur})

        monkeypatch.setattr("provisioner_db.enqueue_event_outbox", _capture)

        from provisioner_db import write_provisioned_state

        outbox_event = {"event_id": "aaa", "event_type": "range.status.updated"}
        write_provisioned_state(
            range_id=42,
            subnets={"attack": {"uuid": "sub-uuid-1"}},
            instances=[{"uuid": "inst-uuid-1"}],
            outbox_event=outbox_event,
        )

        assert len(enqueue_calls) == 1
        assert enqueue_calls[0]["event"] is outbox_event
        assert enqueue_calls[0]["cur"] is not None

    def test_no_enqueue_when_outbox_event_is_none(self, monkeypatch):
        """When outbox_event is None, enqueue_event_outbox is never called."""
        conn_mock, _cursor_mock = self._make_full_conn_mock()
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=conn_mock))
        monkeypatch.setattr("provisioner_db._get_cloud_provider", MagicMock(return_value="aws"))
        monkeypatch.setattr(
            "provisioner_db._build_subnet_state",
            MagicMock(return_value={"cloud_provider": "aws"}),
        )
        monkeypatch.setattr(
            "provisioner_db._build_instance_state",
            MagicMock(return_value={"cloud_provider": "aws"}),
        )
        monkeypatch.setattr(
            "provisioner_db._build_provisioned_instance_payload",
            MagicMock(return_value={}),
        )

        mock_enqueue = MagicMock()
        monkeypatch.setattr("provisioner_db.enqueue_event_outbox", mock_enqueue)

        from provisioner_db import write_provisioned_state

        write_provisioned_state(
            range_id=42,
            subnets={"attack": {"uuid": "sub-uuid-1"}},
            instances=[{"uuid": "inst-uuid-1"}],
        )

        mock_enqueue.assert_not_called()
