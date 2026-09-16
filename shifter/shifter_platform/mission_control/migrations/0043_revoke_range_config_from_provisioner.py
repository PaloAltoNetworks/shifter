# Revoke the provisioner's range_config write capability (ADR-043-R6, #1838).
#
# Migration 0038 granted UPDATE (range_config) so the provisioner could write
# realized subnet CIDRs back into the authored range spec and read them again at
# destroy. That conflated two different things: range_config is authored/compiled
# intent, and realized CIDRs are allocation state.
#
# Phase 6 separates them. Reservation results now come from the Engine-owned
# coordination routines (engine migration 0046) -- reserved before Terraform runs,
# read back at destroy from the same owned allocation rows -- so nothing needs to
# mutate authored intent, and the grant that allowed it goes.
#
# Migration 0038 is history, not an edit target (ADR-043: forward migrations only).

from django.db import migrations

_ROLE = "provisioner_lambda"

# Written as a literal: the table, column and role are fixed at authoring time,
# and DDL cannot bind identifiers as parameters.
_REVOKE_RANGE_CONFIG_UPDATE = "REVOKE UPDATE (range_config) ON mission_control_range FROM provisioner_lambda;"
_GRANT_RANGE_CONFIG_UPDATE = "GRANT UPDATE (range_config) ON mission_control_range TO provisioner_lambda;"


def _applies(schema_editor) -> bool:
    """Return True on PostgreSQL when the role exists (absent in some setups)."""
    if schema_editor.connection.vendor != "postgresql":
        return False
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [_ROLE])
        return cursor.fetchone() is not None


def revoke_range_config_update(apps, schema_editor):
    """Revoke UPDATE on the range_config column from provisioner_lambda."""
    if not _applies(schema_editor):
        return
    schema_editor.execute(_REVOKE_RANGE_CONFIG_UPDATE)


def grant_range_config_update(apps, schema_editor):
    """Restore UPDATE on the range_config column to provisioner_lambda."""
    if not _applies(schema_editor):
        return
    schema_editor.execute(_GRANT_RANGE_CONFIG_UPDATE)


class Migration(migrations.Migration):
    """Revoke the provisioner's authored-intent write capability."""

    dependencies = [
        ("mission_control", "0042_revoke_ngfw_range_grants_from_provisioner"),
    ]

    operations = [
        migrations.RunPython(revoke_range_config_update, grant_range_config_update),
    ]
