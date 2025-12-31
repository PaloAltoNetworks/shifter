# Grant provisioner_lambda user permission to update NGFW columns
#
# The provisioner needs UPDATE permission on NGFW fields to store
# instance details after provisioning VM-Series firewall.

from django.db import migrations


def grant_ngfw_columns(apps, schema_editor):
    """Grant UPDATE permission on NGFW columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        GRANT UPDATE (
            ngfw_enabled,
            ngfw_instance_id,
            ngfw_untrust_ip,
            ngfw_trust_ip
        ) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_ngfw_columns(apps, schema_editor):
    """Revoke UPDATE permission on NGFW columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE UPDATE (
            ngfw_enabled,
            ngfw_instance_id,
            ngfw_untrust_ip,
            ngfw_trust_ip
        ) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant UPDATE permission on NGFW columns to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0019_add_ngfw_fields"),
    ]

    operations = [
        migrations.RunPython(grant_ngfw_columns, revoke_ngfw_columns),
    ]
