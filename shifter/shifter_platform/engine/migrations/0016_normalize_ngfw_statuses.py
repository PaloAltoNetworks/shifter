"""Normalize NGFW instance statuses to match ResourceStatus enum.

The provisioner previously used NGFW-specific status strings (active, stopped,
stopping, starting) instead of the standard ResourceStatus values (ready,
paused, pausing, resuming). This migration updates any existing rows.
"""

from django.db import migrations


def normalize_ngfw_statuses(apps, schema_editor):
    Instance = apps.get_model("engine", "Instance")
    status_map = {
        "active": "ready",
        "stopped": "paused",
        "stopping": "pausing",
        "starting": "resuming",
    }
    for old, new in status_map.items():
        Instance.objects.filter(role="ngfw", status=old).update(status=new)


def revert_ngfw_statuses(apps, schema_editor):
    Instance = apps.get_model("engine", "Instance")
    status_map = {
        "ready": "active",
        "paused": "stopped",
        "pausing": "stopping",
        "resuming": "starting",
    }
    for old, new in status_map.items():
        Instance.objects.filter(role="ngfw", status=old).update(status=new)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0015_add_pausing_status_to_range"),
    ]

    operations = [
        migrations.RunPython(normalize_ngfw_statuses, revert_ngfw_statuses),
    ]
