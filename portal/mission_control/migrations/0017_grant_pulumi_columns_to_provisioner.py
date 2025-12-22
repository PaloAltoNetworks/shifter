# Grant provisioner_lambda user permission to update Pulumi provisioner columns
#
# The 0016_add_pulumi_provisioner_fields migration added columns but didn't
# grant UPDATE permission to provisioner_lambda. This migration fixes that.
#
# Also grants UPDATE on updated_at which was missing from the original grants.

from django.db import migrations


def grant_pulumi_columns(apps, schema_editor):
    """Grant UPDATE permission on Pulumi columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        GRANT UPDATE (
            updated_at,
            provisioned_instances,
            pulumi_stack
        ) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_pulumi_columns(apps, schema_editor):
    """Revoke UPDATE permission on Pulumi columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE UPDATE (
            updated_at,
            provisioned_instances,
            pulumi_stack
        ) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant UPDATE permission on Pulumi columns to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0016_add_pulumi_provisioner_fields"),
    ]

    operations = [
        migrations.RunPython(grant_pulumi_columns, revoke_pulumi_columns),
    ]
