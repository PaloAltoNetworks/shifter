"""Cryptographic integrity coverage for the shared audit ledger."""

from __future__ import annotations

import ast
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import override_settings

from ctf.services.audit import audit_public_registration_publication
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent
from shared.audit.integrity import AuditIntegrityError, verify_audit_chain
from shared.audit_adapter import DjangoAuditLogWriter
from shared.models import AuditChainHead, AuditLog

pytestmark = pytest.mark.django_db


@contextmanager
def _privileged_tamper_access():
    """Simulate the migration-owner authority outside the runtime trust boundary."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE shared_auditlog DISABLE TRIGGER shared_auditlog_append_only")
    try:
        yield
    finally:
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("ALTER TABLE shared_auditlog ENABLE TRIGGER shared_auditlog_append_only")


def _write(*, entity_id: int, entity_ref: str = "", context: str = "") -> AuditLog:
    DjangoAuditLogWriter().write(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=entity_id,
            entity_ref=entity_ref,
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.SYSTEM,
            context=context,
            request_id=f"req-{entity_id}",
        )
    )
    return AuditLog.objects.get(entity_id=entity_id)


def test_every_opaque_audit_target_declares_an_entity_reference():
    platform_root = Path(__file__).resolve().parents[2]
    missing: list[str] = []
    source_paths = (
        path
        for package in ("cms", "ctf", "engine", "mission_control", "shared")
        for path in (platform_root / package).rglob("*.py")
    )
    for path in source_paths:
        relative = path.relative_to(platform_root)
        if "tests" in relative.parts or "migrations" in relative.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
            entity_id = keywords.get("entity_id")
            if not isinstance(entity_id, ast.Constant) or entity_id.value != 0:
                continue
            if "entity_ref" not in keywords:
                missing.append(f"{relative}:{node.lineno}")

    assert missing == []


def test_writer_builds_one_contiguous_verifiable_chain():
    first = _write(entity_id=1, context="first")
    second = _write(entity_id=2, context="second")

    assert first.sequence == 1
    assert first.previous_digest == ""
    assert len(first.record_digest) == 64
    assert second.sequence == 2
    assert second.previous_digest == first.record_digest
    assert len(second.record_digest) == 64
    assert UUID(str(first.event_id))

    head = AuditChainHead.objects.get(singleton=1)
    assert head.last_sequence == second.sequence
    assert head.last_digest == second.record_digest

    result = verify_audit_chain()
    assert result.record_count == 2
    assert result.terminal_digest == second.record_digest


def test_first_append_binds_an_empty_migration_head_to_the_deployment():
    AuditChainHead.objects.filter(singleton=1).update(deployment_scope="migration-time-scope")

    with override_settings(GCP_PROJECT_ID="runtime-scope"):
        row = _write(entity_id=11)

    head = AuditChainHead.objects.get(singleton=1)
    assert row.deployment_scope == "runtime-scope"
    assert head.deployment_scope == "runtime-scope"
    assert verify_audit_chain().record_count == 1


def test_verifier_detects_changed_evidence_without_repairing_it():
    row = _write(entity_id=3, context="original")
    with _privileged_tamper_access():
        AuditLog.objects.filter(pk=row.pk).update(context="tampered")

    with pytest.raises(AuditIntegrityError, match="digest mismatch at sequence 1"):
        verify_audit_chain()

    row.refresh_from_db()
    assert row.context == "tampered"
    assert AuditChainHead.objects.get(singleton=1).last_digest == row.record_digest


def test_verifier_detects_a_missing_record():
    first = _write(entity_id=4)
    _write(entity_id=5)
    with _privileged_tamper_access():
        AuditLog.objects.filter(pk=first.pk).delete()

    with pytest.raises(AuditIntegrityError, match="expected sequence 1"):
        verify_audit_chain()


def test_writer_preserves_opaque_entity_reference_in_digest():
    entity_ref = "7186ccda-b7fb-47f6-9803-dadeae5812ba"
    row = _write(entity_id=7, entity_ref=entity_ref)

    assert row.entity_ref == entity_ref
    assert verify_audit_chain().record_count == 1


def test_writer_canonicalizes_source_ip_before_hashing():
    DjangoAuditLogWriter().write(
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=12,
            action=AuditAction.UPDATE,
            source_ip="2001:0db8:0000:0000:0000:0000:0000:0001",
        )
    )

    row = AuditLog.objects.get()
    row.refresh_from_db()
    assert row.source_ip == "2001:db8::1"
    assert verify_audit_chain().record_count == 1


def test_uuid_backed_audit_emitter_keeps_the_full_reference():
    event_id = uuid4()

    audit_public_registration_publication(actor_id=42, event_id=event_id, enabled=True)

    row = AuditLog.objects.get()
    assert row.entity_ref == str(event_id)
    assert verify_audit_chain().record_count == 1


@pytest.mark.parametrize(
    "event",
    [
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=-1,
            action=AuditAction.UPDATE,
        ),
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=1,
            action=AuditAction.UPDATE,
            context="line one\nline two",
        ),
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=1,
            action=AuditAction.UPDATE,
            new_state={"password": "must-not-enter-evidence"},
        ),
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=1,
            action=AuditAction.UPDATE,
            new_state={"not_finite": float("nan")},
        ),
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=2_147_483_648,
            action=AuditAction.UPDATE,
        ),
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=1,
            action=AuditAction.UPDATE,
            new_state={"access_token": "must-not-enter-evidence"},
        ),
        AuditEvent(
            entity_type=AuditEntityType.RANGE,
            entity_id=1,
            action=AuditAction.UPDATE,
            source_ip="not-an-ip-address",
        ),
    ],
)
def test_writer_rejects_invalid_or_secret_bearing_evidence(event):
    with pytest.raises((TypeError, ValueError)):
        DjangoAuditLogWriter().write(event)

    assert AuditLog.objects.count() == 0
    head = AuditChainHead.objects.first()
    assert head is None or head.last_sequence == 0


def test_audit_verify_command_reports_only_bounded_chain_identity():
    row = _write(entity_id=8, context="private context")
    output = StringIO()

    call_command("audit_verify", stdout=output)

    rendered = output.getvalue()
    assert "Audit chain verified: 1 record" in rendered
    assert row.record_digest in rendered
    assert row.context not in rendered


def test_audit_verify_command_fails_closed_on_tampering():
    row = _write(entity_id=9, context="original evidence")
    with _privileged_tamper_access():
        AuditLog.objects.filter(pk=row.pk).update(context="tampered evidence")

    with pytest.raises(CommandError, match="Audit integrity verification failed"):
        call_command("audit_verify", stdout=StringIO(), stderr=StringIO())


def test_archive_is_deterministic_and_never_deletes_uncheckpointed_rows(monkeypatch):
    row = _write(entity_id=10, context="retained evidence")
    s3_client = MagicMock()
    sts_client = MagicMock()
    sts_client.get_caller_identity.return_value = {"Account": "123456789012"}

    def _client(service_name):
        return {"s3": s3_client, "sts": sts_client}[service_name]

    monkeypatch.setattr("boto3.client", _client)
    monkeypatch.setattr("django.conf.settings.LOGS_BUCKET_NAME", "audit-bucket", raising=False)

    call_command("audit_archive", retention_days=0, batch_size=1)

    uploaded = s3_client.put_object.call_args.kwargs
    assert uploaded["ChecksumSHA256"]
    assert AuditLog.objects.filter(pk=row.pk).exists()
