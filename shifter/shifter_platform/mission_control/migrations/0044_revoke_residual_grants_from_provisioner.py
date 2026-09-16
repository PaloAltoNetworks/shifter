# Revoke legacy mission_control grants the surviving cyberscript path no longer
# needs (ADR-043 phase 7, #1839).
#
# Many of these were granted before tables/columns were dropped or before later
# families cut over to the operation contract. Reconcile against the live catalog
# rather than replaying historical SQL; naming an absent column or table in a
# REVOKE is a hard error in PostgreSQL (see 0042 for the pattern).
#
# The reviewed allowlist of mission_control_range UPDATE columns is enforced by
# TestProvisionerEffectivePrivilegesPostgres, not by this migration alone.

from django.db import migrations

_ROLE = "provisioner_lambda"

# Tables that may still carry a stale SELECT grant even after the model moved or
# was deleted. Revoke only when the relation still exists.
_REVOKE_TABLES = (
    "mission_control_agentconfig",
    "mission_control_operatingsystem",
    "mission_control_ngfwconfig",
    "mission_control_strataconfig",
    "mission_control_scmcredential",
    "mission_control_ngfwdeploymentprofile",
    "mission_control_userngfw",
)

# Column-level UPDATE grants from early range provisioning that no longer map to
# live writers once the cyberscript path was narrowed to the phase-7 allowlist.
_REVOKE_RANGE_COLUMNS = (
    "chat_url",
    "kali_ip",
    "kali_instance_id",
    "kali_ssh_key_secret_arn",
    "ngfw_enabled",
    "ngfw_untrust_ip",
    "ngfw_trust_ip",
    "pulumi_stack",
    "subnet_cidr",
    "subnet_id",
    "victim_instance_id",
    "victim_ip",
    "victim_ssh_key_secret_arn",
)

_TABLE = "mission_control_range"


def _role_exists(schema_editor, role: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        return cursor.fetchone() is not None


def _table_exists(schema_editor, table: str) -> bool:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
            """,
            [table],
        )
        return cursor.fetchone() is not None


def _existing_columns(schema_editor, table: str, columns: tuple[str, ...]) -> list[str]:
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


def _applies(schema_editor) -> bool:
    return schema_editor.connection.vendor == "postgresql" and _role_exists(schema_editor, _ROLE)


def _revoke_table_selects(apps, schema_editor):
    if not _applies(schema_editor):
        return
    for table in _REVOKE_TABLES:
        if _table_exists(schema_editor, table):
            schema_editor.execute(f"REVOKE SELECT ON {table} FROM {_ROLE};")  # nosec B608


def _grant_table_selects(apps, schema_editor):
    if not _applies(schema_editor):
        return
    for table in _REVOKE_TABLES:
        if _table_exists(schema_editor, table):
            schema_editor.execute(f"GRANT SELECT ON {table} TO {_ROLE};")  # nosec B608


def _revoke_legacy_range_columns(apps, schema_editor):
    if not _applies(schema_editor):
        return
    columns = _existing_columns(schema_editor, _TABLE, _REVOKE_RANGE_COLUMNS)
    if not columns:
        return
    schema_editor.execute(
        "REVOKE UPDATE ({columns}) ON {table} FROM {role};".format(
            columns=", ".join(columns),
            table=_TABLE,
            role=_ROLE,
        )
    )  # nosec B608


def _grant_legacy_range_columns(apps, schema_editor):
    if not _applies(schema_editor):
        return
    columns = _existing_columns(schema_editor, _TABLE, _REVOKE_RANGE_COLUMNS)
    if not columns:
        return
    schema_editor.execute(
        "GRANT UPDATE ({columns}) ON {table} TO {role};".format(
            columns=", ".join(columns),
            table=_TABLE,
            role=_ROLE,
        )
    )  # nosec B608


class Migration(migrations.Migration):
    """Revoke legacy mission_control grants outside the phase-7 allowlist."""

    dependencies = [
        ("mission_control", "0043_revoke_range_config_from_provisioner"),
    ]

    operations = [
        migrations.RunPython(_revoke_table_selects, _grant_table_selects),
        migrations.RunPython(_revoke_legacy_range_columns, _grant_legacy_range_columns),
    ]
