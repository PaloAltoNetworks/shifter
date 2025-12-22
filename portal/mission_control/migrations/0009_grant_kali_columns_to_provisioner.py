# Grant provisioner_lambda user permission to update kali columns
#
# The 0006 migration only granted UPDATE on the original columns.
# This migration adds the kali_ip and kali_instance_id columns.

from django.db import migrations


def grant_kali_columns(apps, schema_editor):
    """Grant UPDATE permission on kali columns to provisioner_lambda (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        GRANT UPDATE (kali_ip, kali_instance_id) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_kali_columns(apps, schema_editor):
    """Revoke UPDATE permission on kali columns from provisioner_lambda (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE UPDATE (kali_ip, kali_instance_id) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant UPDATE permission on kali columns to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0008_range_kali_instance_id_range_kali_ip"),
    ]

    operations = [
        migrations.RunPython(grant_kali_columns, revoke_kali_columns),
    ]
