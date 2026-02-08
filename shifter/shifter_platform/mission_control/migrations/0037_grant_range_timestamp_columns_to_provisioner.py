# Grant provisioner_lambda user permission to update range timestamp columns
#
# The provisioner needs UPDATE on these columns to:
# - Set paused_at when pausing a range
# - Set ready_at when resuming a range
# - Set destroyed_at when destroying a range

from django.db import migrations


def grant_timestamp_permissions(apps, schema_editor):
    """Grant UPDATE permissions on range timestamp columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        GRANT UPDATE (
            paused_at,
            ready_at,
            destroyed_at
        ) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_timestamp_permissions(apps, schema_editor):
    """Revoke UPDATE permissions on range timestamp columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        REVOKE UPDATE (
            paused_at,
            ready_at,
            destroyed_at
        ) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant provisioner_lambda UPDATE on range timestamp columns."""

    dependencies = [
        ("mission_control", "0036_grant_range_status_to_provisioner"),
    ]

    operations = [
        migrations.RunPython(grant_timestamp_permissions, revoke_timestamp_permissions),
    ]
