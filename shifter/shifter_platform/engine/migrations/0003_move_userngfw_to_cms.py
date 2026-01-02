"""Move UserNGFW model from engine to cms.

This is a state-only migration - no database changes.
The table remains mission_control_userngfw (same db_table in both apps).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0002_remove_agent_fks_add_range_config"),
        ("cms", "0008_add_userngfw"),
    ]

    operations = [
        # State-only: remove UserNGFW from engine state (now in cms)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="UserNGFW",
                ),
            ],
            database_operations=[],  # No DB changes
        ),
        # Update Range.ngfw FK to point to cms.UserNGFW (state-only)
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="range",
                    name="ngfw",
                    field=models.ForeignKey(
                        blank=True,
                        help_text="Persistent NGFW instance for this range",
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="ranges",
                        to="cms.userngfw",
                    ),
                ),
            ],
            database_operations=[],  # No DB changes - FK already points to same table
        ),
    ]
