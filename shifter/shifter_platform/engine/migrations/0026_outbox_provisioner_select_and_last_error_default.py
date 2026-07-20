# Two fixes required for the provisioner to write the range event outbox on a
# fresh database (found in the #1425 de-novo standup):
#
# 1. GRANT SELECT (#1453). The provisioner enqueues with
#    `INSERT ... ON CONFLICT (event_id) DO NOTHING`, which requires SELECT on the
#    table in addition to INSERT (0025 granted INSERT only), so the enqueue was
#    denied with "permission denied for table engine_range_event_outbox" even
#    though INSERT was granted.
# 2. last_error DB default (#1454). RangeEventOutbox.last_error is
#    `TextField(blank=True, default="")` — a Django app-level default, not a DB
#    default, so the column is NOT NULL with no server default. The portal ORM
#    supplies "" on save, but the provisioner's raw-SQL enqueue omits the column
#    and hit a NOT-NULL violation. Add a server-side default so raw writers honor
#    the model's intended default.

from django.db import migrations


def apply_fixes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        GRANT SELECT ON engine_range_event_outbox TO provisioner_lambda;
        ALTER TABLE engine_range_event_outbox ALTER COLUMN last_error SET DEFAULT '';
        """
    )


def revert_fixes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        ALTER TABLE engine_range_event_outbox ALTER COLUMN last_error DROP DEFAULT;
        REVOKE SELECT ON engine_range_event_outbox FROM provisioner_lambda;
        """
    )


class Migration(migrations.Migration):
    """Grant provisioner_lambda SELECT on the outbox + add last_error DB default."""

    dependencies = [
        ("engine", "0025_grant_range_event_outbox_to_provisioner"),
    ]

    operations = [
        migrations.RunPython(apply_fixes, revert_fixes),
    ]
