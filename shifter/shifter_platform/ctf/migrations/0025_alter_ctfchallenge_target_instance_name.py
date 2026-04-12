"""Align target_instance_name field metadata with the current model."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0024_add_challenge_connection_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ctfchallenge",
            name="target_instance_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Instance name for connection info (e.g. 'windows-target')",
                max_length=100,
            ),
        ),
    ]
