"""Add per-challenge connection info fields."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0023_add_reminder_hours"),
    ]

    operations = [
        migrations.AddField(
            model_name="ctfchallenge",
            name="target_instance_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Instance name to resolve for connection info (e.g. 'windows-target')",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="ctfchallenge",
            name="target_port",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Target port for this challenge (e.g. 80, 3389)",
                null=True,
            ),
        ),
    ]
