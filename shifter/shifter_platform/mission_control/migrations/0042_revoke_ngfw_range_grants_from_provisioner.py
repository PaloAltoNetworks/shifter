# Revoke the provisioner's surviving NGFW column grants on mission_control_range
# (ADR-043 phase 4, #1836).
#
# Migrations 0020 and 0031 granted a wider NGFW surface than survives today, so
# this migration reconciles against the live catalog instead of replaying their
# SQL. Naming an absent column or table in a REVOKE is a hard error in
# PostgreSQL, and several of those objects are gone:
#
#   ngfw_enabled / ngfw_untrust_ip / ngfw_trust_ip  dropped by mission_control
#                                                   0029; grants died with them
#   ngfw_id                                         dropped by engine 0004
#   mission_control_userngfw                        table dropped by cms 0017
#   mission_control_scmcredential                   model deleted by mc 0034
#   mission_control_ngfwdeploymentprofile           model deleted by mc 0034
#
# What actually survives and is safe to revoke here is `gwlb_endpoint_id`: the
# column exists and no provisioner SQL writes it.
#
# `ngfw_instance_id` is deliberately RETAINED. It is still written by
# `provisioner_db.write_provisioned_state` on the cyberscript range provision
# path, which this issue does not cut over. Revoking it would break provisioning;
# it belongs to the residual-grant teardown (#1839).
#
# 0020 and 0031 are evidence of the old capability, not edit targets
# (ADR-043: forward migrations only).

from django.db import migrations

_TABLE = "mission_control_range"
_REVOKE_COLUMNS = ("gwlb_endpoint_id",)
_ROLE = "provisioner_lambda"


def _existing_columns(schema_editor, table: str, columns: tuple[str, ...]) -> list[str]:
    """Return the subset of ``columns`` that exists on ``table`` right now."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = ANY(%s)
            """,
            [table, list(columns)],
        )
        return sorted(row[0] for row in cursor.fetchall())


def _role_exists(schema_editor, role: str) -> bool:
    """Return True when the database role exists (absent in some local setups)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        return cursor.fetchone() is not None


def _apply(schema_editor, statement: str) -> None:
    """Emit ``statement`` for each surviving granted column, if any."""
    if schema_editor.connection.vendor != "postgresql":
        return
    if not _role_exists(schema_editor, _ROLE):
        return
    columns = _existing_columns(schema_editor, _TABLE, _REVOKE_COLUMNS)
    if not columns:
        return
    schema_editor.execute(statement.format(columns=", ".join(columns), table=_TABLE, role=_ROLE))


def revoke_range_ngfw_columns(apps, schema_editor):
    """Revoke UPDATE on the surviving NGFW columns of mission_control_range."""
    _apply(schema_editor, "REVOKE UPDATE ({columns}) ON {table} FROM {role};")


def grant_range_ngfw_columns(apps, schema_editor):
    """Restore UPDATE on those columns (reverse of the revoke)."""
    _apply(schema_editor, "GRANT UPDATE ({columns}) ON {table} TO {role};")


class Migration(migrations.Migration):
    """Revoke the provisioner's surviving NGFW write capability on the range table."""

    dependencies = [
        ("mission_control", "0041_create_portal_runtime_user"),
    ]

    operations = [
        migrations.RunPython(revoke_range_ngfw_columns, grant_range_ngfw_columns),
    ]
