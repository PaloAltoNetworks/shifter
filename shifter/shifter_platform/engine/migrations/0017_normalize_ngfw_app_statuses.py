"""Normalize NGFW app statuses missed by 0016.

Migration 0016 was deployed to dev before it covered engine_app and cms_app.
Since Django recorded 0016 as applied, those two tables were never updated on
dev.  This migration applies the same status mapping to engine_app and cms_app
so dev catches up.  On prod (where 0016 already covers all three tables) these
UPDATEs are safe no-ops because the old values no longer exist.
"""

from django.db import migrations

# (old_status, new_status)
STATUS_MAP = [
    ("active", "ready"),
    ("stopped", "paused"),
    ("stopping", "pausing"),
    ("starting", "resuming"),
]

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
        cursor.execute(SQL_UPDATE_ENGINE_APP, params)
        cursor.execute(SQL_UPDATE_CMS_APP, params)


def normalize_app_statuses(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        _run_status_updates(cursor, STATUS_MAP)


def revert_app_statuses(apps, schema_editor):
    reverse_map = [(new, old) for old, new in STATUS_MAP]
    with schema_editor.connection.cursor() as cursor:
        _run_status_updates(cursor, reverse_map)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0016_normalize_ngfw_statuses"),
    ]

    operations = [
        migrations.RunPython(normalize_app_statuses, revert_app_statuses),
    ]
