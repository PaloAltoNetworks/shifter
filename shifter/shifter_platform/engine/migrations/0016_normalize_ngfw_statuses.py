"""Normalize NGFW instance statuses to match ResourceStatus enum.

The provisioner previously used NGFW-specific status strings (active, stopped,
stopping, starting) instead of the standard ResourceStatus values (ready,
paused, pausing, resuming). This migration updates existing rows across all
three tables that store NGFW status: engine_instance, engine_app, and cms_app.
"""

from django.db import migrations

# (old_status, new_status)
STATUS_MAP = [
    ("active", "ready"),
    ("stopped", "paused"),
    ("stopping", "pausing"),
    ("starting", "resuming"),
]

# engine_app.instance_id is a bigint FK to engine_instance.id
# cms_app.instance_id is a UUID FK to engine_instance.uuid (via cms_instance)
SQL_UPDATE_ENGINE_INSTANCE = (
    "UPDATE engine_instance SET status = %(new)s"
    " WHERE role = 'ngfw' AND status = %(old)s"
)
SQL_UPDATE_ENGINE_APP = (
    "UPDATE engine_app SET status = %(new)s"
    " WHERE status = %(old)s"
    " AND instance_id IN (SELECT id FROM engine_instance WHERE role = 'ngfw')"
)
SQL_UPDATE_CMS_APP = (
    "UPDATE cms_app SET status = %(new)s"
    " WHERE status = %(old)s"
    " AND instance_id IN (SELECT uuid FROM engine_instance WHERE role = 'ngfw')"
)


def _run_status_updates(cursor, status_pairs):
    for old, new in status_pairs:
        params = {"old": old, "new": new}
        cursor.execute(SQL_UPDATE_ENGINE_INSTANCE, params)
        cursor.execute(SQL_UPDATE_ENGINE_APP, params)
        cursor.execute(SQL_UPDATE_CMS_APP, params)


def normalize_ngfw_statuses(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        _run_status_updates(cursor, STATUS_MAP)


def revert_ngfw_statuses(apps, schema_editor):
    reverse_map = [(new, old) for old, new in STATUS_MAP]
    with schema_editor.connection.cursor() as cursor:
        _run_status_updates(cursor, reverse_map)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0015_add_pausing_status_to_range"),
    ]

    operations = [
        migrations.RunPython(normalize_ngfw_statuses, revert_ngfw_statuses),
    ]
