"""Coverage for the ``audit_archive`` command's pre-upload guards.

The archive aborts cleanly before any S3 work when the destination bucket is
unset or boto3 is unavailable; both paths leave the source rows untouched.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from shared.audit import AuditAction, AuditActorType, AuditEntityType
from shared.models import AuditLog

pytestmark = pytest.mark.django_db


def _archivable_audit_log() -> AuditLog:
    """Create one audit row old enough to fall outside the retention window."""
    row = AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=1,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
        context="archivable",
    )
    # ``timestamp`` is auto_now_add; backdate via ``update()`` (which bypasses it)
    # so the row predates the default 90-day cutoff and the command has work to do.
    AuditLog.objects.filter(pk=row.pk).update(timestamp=timezone.now() - timedelta(days=200))
    return row


@override_settings(LOGS_BUCKET_NAME=None, AUDIT_ARCHIVE_BUCKET=None)
def test_aborts_when_bucket_not_configured(monkeypatch):
    """No configured bucket -> _prepare_upload returns None and the archive stops
    before any upload/delete (audit_archive.py:180)."""
    monkeypatch.delenv("LOGS_BUCKET_NAME", raising=False)
    monkeypatch.delenv("AUDIT_ARCHIVE_BUCKET", raising=False)
    _archivable_audit_log()

    out = StringIO()
    call_command("audit_archive", stdout=out)

    assert "LOGS_BUCKET_NAME not configured" in out.getvalue()
    # Aborted before upload/delete: the row survives.
    assert AuditLog.objects.count() == 1


@override_settings(LOGS_BUCKET_NAME="test-archive-bucket")
def test_aborts_when_boto3_not_installed(monkeypatch):
    """boto3 unavailable -> the "not installed" guard aborts the archive
    (audit_archive.py:184-186)."""
    # A ``None`` entry in sys.modules makes ``import boto3`` raise ImportError.
    monkeypatch.setitem(sys.modules, "boto3", None)
    _archivable_audit_log()

    out = StringIO()
    call_command("audit_archive", stdout=out)

    assert "boto3 not installed" in out.getvalue()
    assert AuditLog.objects.count() == 1
