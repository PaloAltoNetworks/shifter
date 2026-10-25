"""Real-PostgreSQL enforcement for the shared audit integrity chain."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction

from shared.audit import AuditAction, AuditEntityType, AuditEvent
from shared.audit.integrity import verify_audit_chain
from shared.audit_adapter import DjangoAuditLogWriter
from shared.models import AuditChainHead, AuditLog

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _concurrent_write(entity_id: int) -> None:
    close_old_connections()
    try:
        DjangoAuditLogWriter().write(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=entity_id,
                action=AuditAction.UPDATE,
                request_id=f"concurrent-{entity_id}",
            )
        )
    finally:
        close_old_connections()


def _has_table_privilege(role: str, table: str, privilege: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(%s, %s, %s)", [role, table, privilege])
        return bool(cursor.fetchone()[0])


def test_concurrent_writers_commit_one_contiguous_chain():
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(_concurrent_write, range(1, 13)))

    assert list(AuditLog.objects.order_by("sequence").values_list("sequence", flat=True)) == list(range(1, 13))
    assert verify_audit_chain().record_count == 12


def test_database_rejects_committed_evidence_mutation():
    _concurrent_write(20)
    row = AuditLog.objects.get()

    with pytest.raises(DatabaseError):
        AuditLog.objects.filter(pk=row.pk).update(context="tampered")
    connection.rollback()

    with pytest.raises(DatabaseError):
        AuditLog.objects.filter(pk=row.pk).delete()
    connection.rollback()

    row.refresh_from_db()
    assert row.context == ""


def test_database_rejects_invalid_chain_head_advance():
    _concurrent_write(21)

    with pytest.raises(DatabaseError):
        AuditChainHead.objects.filter(singleton=1).update(last_sequence=99, last_digest="0" * 64)
    connection.rollback()

    assert AuditChainHead.objects.get(singleton=1).last_sequence == 1


def test_portal_runtime_has_only_the_required_audit_privileges():
    assert _has_table_privilege("portal_runtime", "shared_auditlog", "SELECT")
    assert _has_table_privilege("portal_runtime", "shared_auditlog", "INSERT")
    assert not _has_table_privilege("portal_runtime", "shared_auditlog", "UPDATE")
    assert not _has_table_privilege("portal_runtime", "shared_auditlog", "DELETE")

    assert _has_table_privilege("portal_runtime", "shared_audit_chain_head", "SELECT")
    assert _has_table_privilege("portal_runtime", "shared_audit_chain_head", "UPDATE")
    assert not _has_table_privilege("portal_runtime", "shared_audit_chain_head", "INSERT")
    assert not _has_table_privilege("portal_runtime", "shared_audit_chain_head", "DELETE")


def test_portal_runtime_cannot_disable_guards_or_rewrite_evidence():
    _concurrent_write(30)
    row = AuditLog.objects.get()

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE portal_runtime")
        cursor.execute("ALTER TABLE public.shared_auditlog DISABLE TRIGGER shared_auditlog_append_only")

    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE portal_runtime")
        cursor.execute("UPDATE public.shared_auditlog SET context = 'tampered' WHERE id = %s", [row.pk])

    row.refresh_from_db()
    assert row.context == ""
