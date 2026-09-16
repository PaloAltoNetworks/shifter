"""State-preservation coverage for the audit-table rehome migration."""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from shared.audit import AuditAction, AuditActorType, AuditEntityType
from shared.models import AuditLog

pytestmark = pytest.mark.django_db(transaction=True)

MIGRATION = importlib.import_module("shared.migrations.0006_rehome_audit_log")


def test_upgrade_path_renames_table_and_preserves_rows():
    row = AuditLog.objects.create(
        entity_type=AuditEntityType.RANGE,
        entity_id=71,
        action=AuditAction.PROVISION,
        actor_type=AuditActorType.SYSTEM,
        actor_id=17,
        previous_state={"status": "queued"},
        new_state={"status": "ready"},
        context="preserve me",
        source_ip="192.0.2.71",
        user_agent="migration-test",
        request_id="req-preserved",
    )
    before = AuditLog.objects.values().get(pk=row.pk)
    with connection.schema_editor() as schema_editor:
        for table_name in MIGRATION.RETIRED_TABLES:
            schema_editor.execute(
                f"CREATE TABLE {schema_editor.quote_name(table_name)} (id integer NOT NULL PRIMARY KEY)"
            )
    MigrationRecorder.Migration.objects.create(
        app=MIGRATION.REMOVED_APP_LABEL,
        name="0006_alter_auditlog_action",
    )

    with connection.schema_editor() as schema_editor:
        schema_editor.alter_db_table(AuditLog, MIGRATION.NEW_AUDIT_TABLE, MIGRATION.OLD_AUDIT_TABLE)
        MIGRATION.adopt_or_create_audit_table(apps, schema_editor)

    assert AuditLog.objects.values().get(pk=row.pk) == before
    tables = set(connection.introspection.table_names())
    assert MIGRATION.NEW_AUDIT_TABLE in tables
    assert MIGRATION.OLD_AUDIT_TABLE not in tables
    assert not set(MIGRATION.RETIRED_TABLES) & tables
    assert not MigrationRecorder.Migration.objects.filter(app=MIGRATION.REMOVED_APP_LABEL).exists()


def test_clean_install_path_creates_the_historical_model(monkeypatch):
    created_models = []

    class _SchemaEditor:
        connection = connection
        executed = []

        @staticmethod
        def create_model(model):
            created_models.append(model)

        @staticmethod
        def execute(sql, params=()):
            _SchemaEditor.executed.append((sql, params))

    monkeypatch.setattr(MIGRATION, "_table_names", lambda _schema_editor: set())

    MIGRATION.adopt_or_create_audit_table(apps, _SchemaEditor())

    assert created_models == [AuditLog]
    assert _SchemaEditor.executed == [("DELETE FROM django_migrations WHERE app = %s", [MIGRATION.REMOVED_APP_LABEL])]
