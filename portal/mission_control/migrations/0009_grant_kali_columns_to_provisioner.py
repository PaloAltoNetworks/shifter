# Grant provisioner_lambda user permission to update kali columns
#
# The 0006 migration only granted UPDATE on the original columns.
# This migration adds the kali_ip and kali_instance_id columns.

from django.db import migrations


class Migration(migrations.Migration):
    """Grant UPDATE permission on kali columns to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0008_range_kali_instance_id_range_kali_ip"),
    ]

    operations = [
        migrations.RunSQL(
            # Forward: Grant UPDATE on kali columns
            sql="""
                GRANT UPDATE (kali_ip, kali_instance_id) ON mission_control_range TO provisioner_lambda;
            """,
            # Reverse: Revoke UPDATE on kali columns
            reverse_sql="""
                REVOKE UPDATE (kali_ip, kali_instance_id) ON mission_control_range FROM provisioner_lambda;
            """,
        ),
    ]
