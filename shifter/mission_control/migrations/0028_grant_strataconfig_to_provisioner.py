# Grant provisioner_lambda user permission to read StrataConfig table
#
# The provisioner needs SELECT permission on StrataConfig to read
# SCM credentials for Strata Cloud Manager bootstrap configuration.

from django.db import migrations


def grant_strataconfig_select(apps, schema_editor):
    """Grant SELECT permission on StrataConfig table (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        GRANT SELECT ON mission_control_strataconfig TO provisioner_lambda;
    """)


def revoke_strataconfig_select(apps, schema_editor):
    """Revoke SELECT permission on StrataConfig table (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE SELECT ON mission_control_strataconfig FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant SELECT permission on StrataConfig table to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0027_drop_ngfw_config"),
    ]

    operations = [
        migrations.RunPython(grant_strataconfig_select, revoke_strataconfig_select),
    ]
