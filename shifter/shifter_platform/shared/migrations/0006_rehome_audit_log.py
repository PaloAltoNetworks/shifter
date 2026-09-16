"""Adopt the durable audit table while removing retired feature tables."""

from django.db import migrations, models

OLD_AUDIT_TABLE = "risk" "_register_auditlog"
NEW_AUDIT_TABLE = "shared_auditlog"
REMOVED_APP_LABEL = "risk" "_register"
RETIRED_TABLES = (
    "risk" "_register_comment",
    "risk" "_register_risk",
    "risk" "_register_apikey",
    # Clean up the table name used by the abandoned partial rehome attempt.
    "shared_apikey",
)
OLD_INDEXES = {
    "risk" "_regist_entity__6c222c_idx": ("entity_type", "entity_id"),
    "risk" "_regist_actor_t_bb75e4_idx": ("actor_type", "actor_id"),
    "risk" "_regist_timesta_a16e88_idx": ("timestamp",),
    "risk" "_regist_action_b646cf_idx": ("action",),
}


def _table_names(schema_editor) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        return set(schema_editor.connection.introspection.table_names(cursor))


def _constraint_names(schema_editor, table_name: str) -> set[str]:
    with schema_editor.connection.cursor() as cursor:
        return set(schema_editor.connection.introspection.get_constraints(cursor, table_name))


def adopt_or_create_audit_table(apps, schema_editor):
    """Rename the deployed table or create it on a clean installation."""
    audit_log = apps.get_model("shared", "AuditLog")
    tables = _table_names(schema_editor)
    created = False

    if NEW_AUDIT_TABLE not in tables:
        if OLD_AUDIT_TABLE in tables:
            schema_editor.alter_db_table(audit_log, OLD_AUDIT_TABLE, NEW_AUDIT_TABLE)
        else:
            schema_editor.create_model(audit_log)
            created = True

    # create_model() schedules its indexes on the schema editor; adding them a
    # second time would duplicate them on a clean installation.
    if not created:
        constraints = _constraint_names(schema_editor, NEW_AUDIT_TABLE)
        for index in audit_log._meta.indexes:
            if index.name not in constraints:
                schema_editor.add_index(audit_log, index)

        constraints = _constraint_names(schema_editor, NEW_AUDIT_TABLE)
        for name, fields in OLD_INDEXES.items():
            if name in constraints:
                schema_editor.remove_index(audit_log, models.Index(fields=fields, name=name))

    tables = _table_names(schema_editor)
    for table_name in RETIRED_TABLES:
        if table_name in tables:
            schema_editor.execute(f"DROP TABLE {schema_editor.quote_name(table_name)}")
    schema_editor.execute("DELETE FROM django_migrations WHERE app = %s", [REMOVED_APP_LABEL])


def restore_audit_table_name(apps, schema_editor):
    """Preserve audit evidence if this migration is rolled back."""
    audit_log = apps.get_model("shared", "AuditLog")
    tables = _table_names(schema_editor)
    if NEW_AUDIT_TABLE in tables and OLD_AUDIT_TABLE not in tables:
        schema_editor.alter_db_table(audit_log, NEW_AUDIT_TABLE, OLD_AUDIT_TABLE)


class Migration(migrations.Migration):
    dependencies = [("shared", "0005_alter_acesparticipantruntimerecord_record_kind")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="AuditLog",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "entity_type",
                            models.CharField(
                                choices=[
                                    ("apikey", "API Key"),
                                    ("range", "Range"),
                                    ("credential", "Credential"),
                                    ("agent", "Agent"),
                                    ("user", "User"),
                                    ("session", "Session"),
                                    ("ngfw", "NGFW"),
                                    ("config", "Configuration"),
                                    ("experiment", "Experiment"),
                                    ("scenario", "Scenario"),
                                    ("script", "Script"),
                                ],
                                max_length=20,
                            ),
                        ),
                        ("entity_id", models.PositiveIntegerField()),
                        (
                            "action",
                            models.CharField(
                                choices=[
                                    ("create", "Create"),
                                    ("update", "Update"),
                                    ("delete", "Delete"),
                                    ("restore", "Restore"),
                                    ("close", "Close"),
                                    ("reopen", "Reopen"),
                                    ("login", "Login"),
                                    ("logout", "Logout"),
                                    ("login_failed", "Login Failed"),
                                    ("access_denied", "Access Denied"),
                                    ("role_sync", "Role Sync"),
                                    ("connect", "Connect"),
                                    ("disconnect", "Disconnect"),
                                    ("download", "Download"),
                                    ("provision", "Provision"),
                                    ("deprovision", "Deprovision"),
                                    ("ready", "Ready"),
                                    ("failed", "Failed"),
                                    ("pause", "Pause"),
                                    ("resume", "Resume"),
                                    ("cancel", "Cancel"),
                                    ("recover", "Recover"),
                                    ("spare_provision", "Spare Provision"),
                                ],
                                max_length=20,
                            ),
                        ),
                        (
                            "actor_type",
                            models.CharField(
                                choices=[
                                    ("user", "User"),
                                    ("apikey", "API Key"),
                                    ("system", "System"),
                                    ("cognito", "Cognito"),
                                ],
                                max_length=10,
                            ),
                        ),
                        ("actor_id", models.PositiveIntegerField(blank=True, null=True)),
                        ("timestamp", models.DateTimeField(auto_now_add=True)),
                        ("previous_state", models.JSONField(blank=True, null=True)),
                        ("new_state", models.JSONField(blank=True, null=True)),
                        (
                            "context",
                            models.TextField(blank=True, help_text="Optional reason or notes"),
                        ),
                        ("source_ip", models.GenericIPAddressField(blank=True, null=True)),
                        ("user_agent", models.CharField(blank=True, max_length=500)),
                        (
                            "request_id",
                            models.CharField(blank=True, db_index=True, max_length=64),
                        ),
                    ],
                    options={
                        "db_table": NEW_AUDIT_TABLE,
                        "ordering": ["-timestamp"],
                        "verbose_name": "Audit Log",
                        "verbose_name_plural": "Audit Logs",
                        "indexes": [
                            models.Index(
                                fields=["entity_type", "entity_id"],
                                name="shared_audit_entity_idx",
                            ),
                            models.Index(
                                fields=["actor_type", "actor_id"],
                                name="shared_audit_actor_idx",
                            ),
                            models.Index(fields=["timestamp"], name="shared_audit_timestamp_idx"),
                            models.Index(fields=["action"], name="shared_audit_action_idx"),
                        ],
                    },
                )
            ],
            database_operations=[],
        ),
        migrations.RunPython(adopt_or_create_audit_table, restore_audit_table_name),
    ]
