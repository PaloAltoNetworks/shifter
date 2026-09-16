# Revoke the provisioner's UPDATE on engine_app (ADR-043 phase 4, #1836).
#
# Every NGFW-family writer of engine_app now reports results to the Engine
# result inbox instead of writing the table:
#   - range pause/resume cascade   range_ops/_ngfw.py
#   - direct provision/deprovision/start/stop   ngfw_runtime.update_instance_state
#   - range attachment bookkeeping  now scoped to engine_instance.state only
#     (ngfw_runtime.update_ngfw_attachment_state); it previously re-wrote the
#     NGFW's current status onto the App as a no-op side effect.
#
# Deliberately narrower than "revoke migration 0012":
#   - engine_app SELECT is retained: still read by the provisioner's NGFW
#     lookups (ngfw_runtime, provisioner_db_ngfw, range_ops/_ngfw).
#   - engine_instance UPDATE is retained: still written by cyberscript range
#     provision (provisioner_db._write_instance_states) and by attachment-state
#     bookkeeping. That family is not cut over by this issue.
# Revoking either here would break a live writer. Migration 0012 is evidence of
# the old capability, not an edit target (ADR-043: forward migrations only).

from django.db import migrations

_ROLE = "provisioner_lambda"


def _role_exists(schema_editor) -> bool:
    """Return True when the database role exists (absent in some local setups)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [_ROLE])
        return cursor.fetchone() is not None


def revoke_engine_app_update(apps, schema_editor):
    """Revoke UPDATE on engine_app from provisioner_lambda (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql" or not _role_exists(schema_editor):
        return
    schema_editor.execute(f"REVOKE UPDATE ON engine_app FROM {_ROLE};")


def grant_engine_app_update(apps, schema_editor):
    """Restore UPDATE on engine_app to provisioner_lambda (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql" or not _role_exists(schema_editor):
        return
    schema_editor.execute(f"GRANT UPDATE ON engine_app TO {_ROLE};")


class Migration(migrations.Migration):
    """Revoke the NGFW family's engine_app write capability from the provisioner."""

    dependencies = [
        ("engine", "0038_operation_result_step"),
    ]

    operations = [
        migrations.RunPython(revoke_engine_app_update, grant_engine_app_update),
    ]
