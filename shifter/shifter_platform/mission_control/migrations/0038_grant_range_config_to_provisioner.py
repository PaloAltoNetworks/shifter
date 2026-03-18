# Grant provisioner_lambda user permission to update range_config
#
# The provisioner needs UPDATE on range_config to persist allocated subnet
# CIDRs after provisioning, so that destroy can read them later.

from django.db import migrations


def grant_range_config_update(apps, schema_editor):
    """Grant UPDATE on range_config column (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        GRANT UPDATE (range_config) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_range_config_update(apps, schema_editor):
    """Revoke UPDATE on range_config column (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        REVOKE UPDATE (range_config) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant provisioner_lambda UPDATE on range_config column."""

    dependencies = [
        ("mission_control", "0037_grant_range_timestamp_columns_to_provisioner"),
    ]

    operations = [
        migrations.RunPython(grant_range_config_update, revoke_range_config_update),
    ]
