"""Expand event lifecycle to 7 states (CTF-701).

Renames: scheduled -> registration, completed -> ended.
Adds: paused, archived.
"""

from django.db import migrations, models


def rename_statuses_forward(apps, schema_editor):
    """Rename scheduled -> registration and completed -> ended."""
    CTFEvent = apps.get_model("ctf", "CTFEvent")
    CTFEvent.objects.filter(status="scheduled").update(status="registration")
    CTFEvent.objects.filter(status="completed").update(status="ended")


def rename_statuses_reverse(apps, schema_editor):
    """Reverse: registration -> scheduled and ended -> completed."""
    CTFEvent = apps.get_model("ctf", "CTFEvent")
    CTFEvent.objects.filter(status="registration").update(status="scheduled")
    CTFEvent.objects.filter(status="ended").update(status="completed")
    # paused -> draft (safe fallback) and archived -> completed (closest match)
    CTFEvent.objects.filter(status="paused").update(status="draft")
    CTFEvent.objects.filter(status="archived").update(status="completed")


class Migration(migrations.Migration):

    dependencies = [
        ("ctf", "0007_merge_0006"),
    ]

    operations = [
        # Data migration first — rename existing values
        migrations.RunPython(rename_statuses_forward, rename_statuses_reverse),
        # Schema migration — update choices
        migrations.AlterField(
            model_name="ctfevent",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("registration", "Registration"),
                    ("active", "Active"),
                    ("paused", "Paused"),
                    ("ended", "Ended"),
                    ("cancelled", "Cancelled"),
                    ("archived", "Archived"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
    ]
