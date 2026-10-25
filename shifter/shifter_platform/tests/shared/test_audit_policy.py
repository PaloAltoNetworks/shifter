"""Behavioral coverage for the shared audit policy and attribution boundary."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
    AuditEvent,
    AuditTarget,
    SessionInfo,
    audit_log,
    audit_log_from_request,
    audit_session_event,
    get_audit_health_snapshot,
    reset_audit_health,
)
from shared.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_audit_health_state():
    reset_audit_health()
    yield
    reset_audit_health()


def _unserializable_event() -> AuditEvent:
    return AuditEvent(
        entity_type=AuditEntityType.RANGE,
        entity_id=1,
        action=AuditAction.CREATE,
        new_state={"not-json": {1, 2, 3}},
    )


def test_best_effort_failure_returns_false_and_marks_health_degraded():
    assert audit_log(_unserializable_event()) is False

    snapshot = get_audit_health_snapshot()
    assert snapshot.degraded is True
    assert snapshot.failure_count == 1
    assert snapshot.last_failure_reason == "TypeError"


def test_strict_failure_reraises_after_marking_health_degraded():
    event = _unserializable_event()

    with pytest.raises(TypeError):
        audit_log(event, strict=True)

    snapshot = get_audit_health_snapshot()
    assert snapshot.degraded is True
    assert snapshot.failure_count == 1
    assert snapshot.last_failure_reason == "TypeError"


def test_request_writer_preserves_trusted_attribution():
    request = Mock()
    request.user = Mock(pk=42, id=42, is_authenticated=True)
    request.auth = None
    request.request_id = None
    request.META = {
        "HTTP_X_FORWARDED_FOR": "192.0.2.10, 198.51.100.7",
        "HTTP_USER_AGENT": "audit-policy-test",
        "HTTP_X_REQUEST_ID": "req-audit-policy",
        "REMOTE_ADDR": "127.0.0.1",
    }

    assert audit_log_from_request(
        request,
        AuditTarget(AuditEntityType.RANGE, 42, "range-external-42"),
        action=AuditAction.UPDATE,
    )

    stored = AuditLog.objects.get(entity_type=AuditEntityType.RANGE, entity_id=42)
    assert stored.actor_type == AuditActorType.USER
    assert stored.actor_id == 42
    assert stored.source_ip == "198.51.100.7"
    assert stored.user_agent == "audit-policy-test"
    assert stored.request_id == "req-audit-policy"
    assert stored.entity_ref == "range-external-42"


def test_session_writer_uses_the_opaque_session_id_as_its_target():
    assert audit_session_event(
        AuditAction.CONNECT,
        user_id=42,
        session=SessionInfo(session_id="session-opaque-1", range_id=7, session_type="terminal"),
    )

    stored = AuditLog.objects.get(entity_type=AuditEntityType.SESSION)
    assert stored.entity_id == 0
    assert stored.entity_ref == "session-opaque-1"
