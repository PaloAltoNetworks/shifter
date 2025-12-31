# Grant provisioner_lambda user permission to read NGFWConfig table
#
# The provisioner needs SELECT permission on NGFWConfig to read
# Panorama credentials for VM-Series bootstrap configuration.

from django.db import migrations


def grant_ngfwconfig_select(apps, schema_editor):
    """Grant SELECT permission on NGFWConfig table (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        GRANT SELECT ON mission_control_ngfwconfig TO provisioner_lambda;
    """)


def revoke_ngfwconfig_select(apps, schema_editor):
    """Revoke SELECT permission on NGFWConfig table (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE SELECT ON mission_control_ngfwconfig FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant SELECT permission on NGFWConfig table to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0022_range_ngfw_config"),
    ]

    operations = [
        migrations.RunPython(grant_ngfwconfig_select, revoke_ngfwconfig_select),
    ]
