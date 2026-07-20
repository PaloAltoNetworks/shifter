"""Tests for the risk_register audit persistence adapter (#1523)."""

from __future__ import annotations

import pytest

from risk_register.audit_adapter import DjangoAuditLogWriter, audit_log_writer
from risk_register.models import AuditLog
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent


@pytest.mark.django_db
def test_writer_persists_event_to_auditlog_row():
    writer = DjangoAuditLogWriter()
    writer.write(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=7,
            action=AuditAction.PROVISION,
            actor_type=AuditActorType.SYSTEM,
            context="adapter test",
        )
    )
    stored = AuditLog.objects.get(entity_type=AuditEntityType.RANGE, entity_id=7)
    assert stored.action == AuditAction.PROVISION
    assert stored.actor_type == AuditActorType.SYSTEM
    assert stored.context == "adapter test"


@pytest.mark.django_db
def test_writer_raises_on_unserializable_state():
    """The adapter surfaces persistence faults; it never swallows them."""
    django_audit_log_writer = DjangoAuditLogWriter()
    audit_event = AuditEvent(
        entity_type=AuditEntityType.RANGE,
        entity_id=1,
        action=AuditAction.CREATE,
        new_state={"bad": {1, 2, 3}},
    )
    with pytest.raises(TypeError):
        django_audit_log_writer.write(audit_event)


def test_module_singleton_is_a_writer():
    assert isinstance(audit_log_writer, DjangoAuditLogWriter)
