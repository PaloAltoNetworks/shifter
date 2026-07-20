"""Structured restart logging for CloudWatch metric filters (issue #274)."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import pytest

from config.logging import ECSFormatter
from shared.management.commands.run_worker import Command


@pytest.fixture
def restart_log_capture():
    records: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _ListHandler()
    worker_logger = logging.getLogger("shared.management.commands.run_worker")
    worker_logger.addHandler(handler)
    worker_logger.setLevel(logging.WARNING)
    yield records
    worker_logger.removeHandler(handler)


def test_restart_warning_includes_worker_queue_label(restart_log_capture) -> None:
    heartbeat = Path(tempfile.gettempdir()) / "worker-cms-heartbeat-test-274"
    heartbeat.write_text("stale", encoding="utf-8")
    try:
        command = Command()
        command.queue_name = "cms"
        command.heartbeat_file = heartbeat
        command._check_restart_indicator()

        assert len(restart_log_capture) == 1
        record = restart_log_capture[0]
        assert record.levelname == "WARNING"
        assert "Worker restart detected" in record.getMessage()
        assert getattr(record, "worker_queue", None) == "cms"

        payload = json.loads(ECSFormatter(environment="dev").format(record))
        assert payload["labels.worker_queue"] == "cms"
    finally:
        heartbeat.unlink(missing_ok=True)


def test_no_restart_log_when_heartbeat_absent(restart_log_capture) -> None:
    command = Command()
    command.queue_name = "cms"
    command.heartbeat_file = Path(tempfile.gettempdir()) / "worker-cms-heartbeat-missing-274"
    command._check_restart_indicator()

    assert restart_log_capture == []
