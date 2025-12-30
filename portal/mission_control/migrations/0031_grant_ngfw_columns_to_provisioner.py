# Grant provisioner_lambda user permission to access NGFW-related tables and columns
#
# The provisioner needs:
# - SELECT on SCMCredential to read SCM registration info for NGFW bootstrapping
# - SELECT on NGFWDeploymentProfile to read authcodes for NGFW licensing
# - SELECT/UPDATE on UserNGFW to read config and write back AWS resource IDs
# - UPDATE on Range for ngfw FK and gwlb_endpoint_id

from django.db import migrations


def grant_ngfw_permissions(apps, schema_editor):
    """Grant permissions on NGFW tables (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    # SELECT on credential tables (read-only for provisioner)
    schema_editor.execute("""
        GRANT SELECT ON mission_control_scmcredential TO provisioner_lambda;
    """)
    schema_editor.execute("""
        GRANT SELECT ON mission_control_ngfwdeploymentprofile TO provisioner_lambda;
    """)

    # SELECT and UPDATE on UserNGFW (provisioner reads config, writes back resource IDs)
    schema_editor.execute("""
        GRANT SELECT ON mission_control_userngfw TO provisioner_lambda;
    """)
    schema_editor.execute("""
        GRANT UPDATE (
            status,
            instance_id,
            mgmt_eni_id,
            data_eni_id,
            management_ip,
            dataplane_ip,
            gwlb_arn,
            target_group_arn,
            gwlb_service_name,
            serial_number,
            device_cert_status,
            xdr_configured,
            provisioned_at,
            last_started_at,
            last_stopped_at
        ) ON mission_control_userngfw TO provisioner_lambda;
    """)

    # UPDATE on Range for NGFW-related columns
    schema_editor.execute("""
        GRANT UPDATE (
            ngfw_id,
            gwlb_endpoint_id
        ) ON mission_control_range TO provisioner_lambda;
    """)


def revoke_ngfw_permissions(apps, schema_editor):
    """Revoke permissions on NGFW tables (PostgreSQL only)."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute("""
        REVOKE SELECT ON mission_control_scmcredential FROM provisioner_lambda;
    """)
    schema_editor.execute("""
        REVOKE SELECT ON mission_control_ngfwdeploymentprofile FROM provisioner_lambda;
    """)
    schema_editor.execute("""
        REVOKE SELECT, UPDATE ON mission_control_userngfw FROM provisioner_lambda;
    """)
    schema_editor.execute("""
        REVOKE UPDATE (ngfw_id, gwlb_endpoint_id) ON mission_control_range FROM provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Grant NGFW-related permissions to provisioner_lambda."""

    dependencies = [
        ("mission_control", "0030_ngfw_models"),
    ]

    operations = [
        migrations.RunPython(grant_ngfw_permissions, revoke_ngfw_permissions),
    ]
