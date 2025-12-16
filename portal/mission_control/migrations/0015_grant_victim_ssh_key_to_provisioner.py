# Grant provisioner_lambda user permission to update victim_ssh_key_secret_arn column
#
# The 0012_range_victim_ssh_key_secret_arn migration added the column but didn't
# grant UPDATE permission to provisioner_lambda. This migration fixes that.

from django.db import migrations


class Migration(migrations.Migration):
    """Grant UPDATE permission on victim_ssh_key_secret_arn to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0014_rename_mcp_user_to_kali_mcp_user"),
    ]

    operations = [
        migrations.RunSQL(
            # Forward: Grant UPDATE on victim_ssh_key_secret_arn column
            sql="""
                GRANT UPDATE (victim_ssh_key_secret_arn) ON mission_control_range TO provisioner_lambda;
            """,
            # Reverse: Revoke UPDATE on victim_ssh_key_secret_arn column
            reverse_sql="""
                REVOKE UPDATE (victim_ssh_key_secret_arn) ON mission_control_range FROM provisioner_lambda;
            """,
        ),
    ]
