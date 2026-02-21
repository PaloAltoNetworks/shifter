"""Add agent_type field to AgentConfig model.

Adds support for different agent types: XDR, XDR Collector, Cloud Identity Engine.
Existing agents default to 'xdr' (XDR/XSIAM Agent).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0022_add_scenario_and_metadata_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentconfig",
            name="agent_type",
            field=models.CharField(
                choices=[
                    ("xdr", "XDR/XSIAM Agent"),
                    ("xdr_collector", "XDR Collector"),
                    ("cloud_identity_engine", "Cloud Identity Engine"),
                ],
                default="xdr",
                help_text="Type of agent (XDR, XDR Collector, Cloud Identity Engine)",
                max_length=30,
            ),
        ),
    ]
