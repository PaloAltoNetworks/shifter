"""Tests for the neutral audit writer port and its fail-closed binding (#1523)."""

from __future__ import annotations

import pytest

from shared.audit import AuditEvent
from shared.audit.port import (
    AuditWriter,
    AuditWriterBindingError,
    bind_audit_writer,
    get_audit_writer,
    reset_audit_writer,
)


class _RecordingWriter:
    """Minimal AuditWriter implementation that records events in memory."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _restore_binding():
    """Save and restore the real startup binding around each test."""
    try:
        original = get_audit_writer()
    except AuditWriterBindingError:
        original = None
    reset_audit_writer()
    yield
    reset_audit_writer()
    if original is not None:
        bind_audit_writer(original)


def test_get_without_binding_raises():
    with pytest.raises(AuditWriterBindingError):
        get_audit_writer()


def test_bind_then_get_returns_same_instance():
    writer = _RecordingWriter()
    bind_audit_writer(writer)
    assert get_audit_writer() is writer


def test_binding_same_instance_twice_is_idempotent():
    writer = _RecordingWriter()
    bind_audit_writer(writer)
    bind_audit_writer(writer)  # no error
    assert get_audit_writer() is writer


def test_binding_conflicting_instance_fails_closed():
    bind_audit_writer(_RecordingWriter())
    recording_writer = _RecordingWriter()
    with pytest.raises(AuditWriterBindingError):
        bind_audit_writer(recording_writer)


def test_reset_clears_binding():
    bind_audit_writer(_RecordingWriter())
    reset_audit_writer()
    with pytest.raises(AuditWriterBindingError):
        get_audit_writer()


def test_recording_writer_satisfies_protocol():
    assert isinstance(_RecordingWriter(), AuditWriter)
