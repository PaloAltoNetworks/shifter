# Drop StrataConfig model and related Range fields
# StrataConfig is superseded by SCMCredential and NGFWDeploymentProfile (issue #412)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("mission_control", "0028_grant_strataconfig_to_provisioner"),
    ]

    operations = [
        # Remove FK from Range first (must come before deleting the model)
        migrations.RemoveField(
            model_name="range",
            name="strata_config",
        ),
        # Remove old NGFW fields that were per-range (now handled by UserNGFW)
        migrations.RemoveField(
            model_name="range",
            name="ngfw_enabled",
        ),
        migrations.RemoveField(
            model_name="range",
            name="ngfw_instance_id",
        ),
        migrations.RemoveField(
            model_name="range",
            name="ngfw_untrust_ip",
        ),
        migrations.RemoveField(
            model_name="range",
            name="ngfw_trust_ip",
        ),
        # Then drop the table
        migrations.DeleteModel(
            name="StrataConfig",
        ),
    ]
