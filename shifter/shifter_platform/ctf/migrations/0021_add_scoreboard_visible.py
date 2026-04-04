"""Add scoreboard_visible field to CTFEvent."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0020_add_brackets"),
    ]

    operations = [
        migrations.AddField(
            model_name="ctfevent",
            name="scoreboard_visible",
            field=models.BooleanField(
                default=True,
                help_text="Whether the scoreboard is visible to participants. When False, participants see a hidden message.",
            ),
        ),
    ]
