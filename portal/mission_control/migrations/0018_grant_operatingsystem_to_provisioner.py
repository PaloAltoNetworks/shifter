# Grant SELECT on mission_control_operatingsystem to provisioner_lambda
#
# The provisioner needs to JOIN on the operating system table to determine
# whether to provision a Linux or Windows victim based on the agent's OS.

from django.db import migrations


def grant_select(apps, schema_editor):
    """Grant SELECT on operatingsystem table to provisioner_lambda."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        GRANT SELECT ON mission_control_operatingsystem TO provisioner_lambda;
    """)


def revoke_select(apps, schema_editor):
    """Revoke SELECT on operatingsystem table from provisioner_lambda."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE SELECT ON mission_control_operatingsystem FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant provisioner access to operating system table for Windows support."""

    dependencies = [
        ("mission_control", "0017_grant_pulumi_columns_to_provisioner"),
    ]

    operations = [
        migrations.RunPython(grant_select, revoke_select),
    ]
