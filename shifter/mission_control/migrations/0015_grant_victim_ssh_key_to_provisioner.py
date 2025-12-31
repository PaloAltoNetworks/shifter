# Grant provisioner_lambda user permission to update victim_ssh_key_secret_arn column
#
# The 0012_range_victim_ssh_key_secret_arn migration added the column but didn't
# grant UPDATE permission to provisioner_lambda. This migration fixes that.

from django.db import migrations


def grant_victim_ssh_key(apps, schema_editor):
    """Grant UPDATE permission on victim_ssh_key_secret_arn (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        GRANT UPDATE (victim_ssh_key_secret_arn) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_victim_ssh_key(apps, schema_editor):
    """Revoke UPDATE permission on victim_ssh_key_secret_arn (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE UPDATE (victim_ssh_key_secret_arn) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant UPDATE permission on victim_ssh_key_secret_arn to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0012_range_victim_ssh_key_secret_arn"),
        ("mission_control", "0012_add_cognito_sub_to_userprofile"),
    ]

    operations = [
        migrations.RunPython(grant_victim_ssh_key, revoke_victim_ssh_key),
    ]
