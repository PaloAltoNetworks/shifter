# Grant provisioner_lambda user permission to update range status and related columns
#
# The provisioner needs UPDATE on these columns to:
# - Update status after provisioning/destroying (status, updated_at)
# - Store provisioned instance data (provisioned_instances, ngfw_instance_id)
# - Set error_message on failure

from django.db import migrations

_TABLE = "mission_control_range"
_ROLE = "provisioner_lambda"
_LEGACY_COLUMNS = (
    "status",
    "updated_at",
    "provisioned_instances",
    "ngfw_instance_id",
    "error_message",
)


def _apply_existing_columns(schema_editor, action):
    """Apply the historical grant only to columns surviving this migration graph."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = ANY(%s)
            """,
            [_TABLE, list(_LEGACY_COLUMNS)],
        )
        columns = sorted(row[0] for row in cursor.fetchall())
    if columns:
        schema_editor.execute(
            f"{action} UPDATE ({', '.join(columns)}) ON {_TABLE} {'TO' if action == 'GRANT' else 'FROM'} {_ROLE};"
        )  # nosec B608 -- identifiers come only from the closed constants above


def grant_range_status_permissions(apps, schema_editor):
    """Grant UPDATE permissions on range columns (PostgreSQL only)."""
    _apply_existing_columns(schema_editor, "GRANT")


def revoke_range_status_permissions(apps, schema_editor):
    """Revoke UPDATE permissions on range columns (PostgreSQL only)."""
    _apply_existing_columns(schema_editor, "REVOKE")


class Migration(migrations.Migration):
    """Grant provisioner_lambda UPDATE on range status columns."""

    dependencies = [
        ("mission_control", "0035_move_models_to_engine"),
    ]

    operations = [
        migrations.RunPython(grant_range_status_permissions, revoke_range_status_permissions),
    ]
