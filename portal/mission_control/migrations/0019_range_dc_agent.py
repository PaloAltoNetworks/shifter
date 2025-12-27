# Add dc_agent field to Range for separate DC agent selection in AD scenarios
#
# This allows users to select different agents for:
# - Victim instances (any OS)
# - DC instances (must be Windows/MSI)
#
# Note: No column-level grants needed - provisioner_lambda already has SELECT
# on mission_control_range table from earlier migrations.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Add dc_agent FK to Range for AD scenario agent selection."""

    dependencies = [
        ("mission_control", "0018_grant_operatingsystem_to_provisioner"),
    ]

    operations = [
        migrations.AddField(
            model_name="range",
            name="dc_agent",
            field=models.ForeignKey(
                blank=True,
                help_text="Agent for DC instances (Windows only, required for AD scenarios)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dc_ranges",
                to="mission_control.agentconfig",
            ),
        ),
        migrations.AlterField(
            model_name="range",
            name="agent",
            field=models.ForeignKey(
                blank=True,
                help_text="Agent for victim instances",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ranges",
                to="mission_control.agentconfig",
            ),
        ),
    ]
