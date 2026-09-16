from django.db import migrations


def grant_vpn_access_binding(apps, schema_editor):
    """Allow the provisioner to persist the non-secret OpenVPN binding."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("GRANT UPDATE (vpn_access_binding) ON mission_control_range TO provisioner_lambda;")


def revoke_vpn_access_binding(apps, schema_editor):
    """Remove the provisioner's OpenVPN binding write permission."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("REVOKE UPDATE (vpn_access_binding) ON mission_control_range FROM provisioner_lambda;")


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0033_feature_delivery_binding_identity"),
    ]

    operations = [
        migrations.RunPython(grant_vpn_access_binding, revoke_vpn_access_binding),
    ]
