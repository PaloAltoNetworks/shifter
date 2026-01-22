# Grant provisioner_lambda user permission to update range status and related columns
#
# The provisioner needs UPDATE on these columns to:
# - Update status after provisioning/destroying (status, updated_at)
# - Store provisioned instance data (provisioned_instances, ngfw_instance_id)
# - Set error_message on failure

from django.db import migrations


def grant_range_status_permissions(apps, schema_editor):
    """Grant UPDATE permissions on range columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        GRANT UPDATE (
            status,
            updated_at,
            provisioned_instances,
            ngfw_instance_id,
            error_message
        ) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_range_status_permissions(apps, schema_editor):
    """Revoke UPDATE permissions on range columns (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        REVOKE UPDATE (
            status,
            updated_at,
            provisioned_instances,
            ngfw_instance_id,
            error_message
        ) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant provisioner_lambda UPDATE on range status columns."""

    dependencies = [
        ("mission_control", "0035_move_models_to_engine"),
    ]

    operations = [
        migrations.RunPython(grant_range_status_permissions, revoke_range_status_permissions),
    ]
