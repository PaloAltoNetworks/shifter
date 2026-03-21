"""Add programmable and HTTP flag validation support to CTFFlag.

Extends flag_type choices and adds validator_config JSONField for
per-flag validator configuration (CTF-118).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ctf", "0004_ctfaward"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ctfflag",
            name="flag_type",
            field=models.CharField(
                choices=[
                    ("static", "Static (hashed comparison)"),
                    ("regex", "Regex (pattern match)"),
                    ("programmable", "Programmable (custom validator)"),
                    ("http", "HTTP (external endpoint)"),
                ],
                default="static",
                help_text="Flag verification type",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="ctfflag",
            name="validator_config",
            field=models.JSONField(
                blank=True,
                default=None,
                help_text="Configuration for programmable/http validators",
                null=True,
            ),
        ),
    ]
