"""Restore the provisioner's range-to-NGFW attachment write grant.

The historical grant runs before ``engine.0014`` adds ``ngfw_instance_id`` to
the shared range table.  On a fresh database that ordering leaves the column
without the grant required by the surviving provisioner writer.  Reconcile the
grant after both migration branches have completed.
"""

from django.db import migrations

_COLUMN = "ngfw_instance_id"
_ROLE = "provisioner_lambda"
_TABLE = "mission_control_range"


def _role_exists(schema_editor) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [_ROLE])
        return cursor.fetchone() is not None


def _column_exists(schema_editor) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            [_TABLE, _COLUMN],
        )
        return cursor.fetchone() is not None


def grant_range_ngfw_instance_update(apps, schema_editor) -> None:
    """Restore the narrow write needed by the provisioner lifecycle path."""
    if schema_editor.connection.vendor != "postgresql":
        return
    if _role_exists(schema_editor) and _column_exists(schema_editor):
        schema_editor.execute(f"GRANT UPDATE ({_COLUMN}) ON {_TABLE} TO {_ROLE};")


def revoke_range_ngfw_instance_update(apps, schema_editor) -> None:
    """Reverse the reconciliation without changing any other column grant."""
    if schema_editor.connection.vendor != "postgresql":
        return
    if _role_exists(schema_editor) and _column_exists(schema_editor):
        schema_editor.execute(f"REVOKE UPDATE ({_COLUMN}) ON {_TABLE} FROM {_ROLE};")


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0083_reconcile_subnet_coordination_grants"),
    ]

    operations = [
        migrations.RunPython(grant_range_ngfw_instance_update, revoke_range_ngfw_instance_update),
    ]
