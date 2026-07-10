# Grant provisioner_lambda INSERT on the range event outbox (#1453).
#
# The provisioner publishes range status updates through the transactional
# outbox (engine_range_event_outbox, added in 0023 for #476): every
# provision/teardown status transition calls provisioner_db.enqueue_event_outbox,
# which INSERTs a row. provisioner_lambda was never granted INSERT on that table,
# so on a fresh database range provisioning fails with
# "permission denied for table engine_range_event_outbox" and rolls back — no
# range can launch. Grant INSERT on the table plus USAGE on its BigAutoField
# sequence (needed for the id default on INSERT). The portal-side reconciler /
# drainer read and update the outbox under the portal runtime role, not the
# provisioner, so the provisioner needs INSERT only.

from django.db import migrations


def grant_permissions(apps, schema_editor):
    """Grant provisioner_lambda INSERT on the range event outbox."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        GRANT INSERT ON engine_range_event_outbox TO provisioner_lambda;
        GRANT USAGE ON SEQUENCE engine_range_event_outbox_id_seq TO provisioner_lambda;
        """
    )


def revoke_permissions(apps, schema_editor):
    """Revoke provisioner_lambda access to the range event outbox."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        REVOKE INSERT ON engine_range_event_outbox FROM provisioner_lambda;
        REVOKE USAGE ON SEQUENCE engine_range_event_outbox_id_seq FROM provisioner_lambda;
        """
    )


class Migration(migrations.Migration):
    """Grant provisioner_lambda INSERT on engine_range_event_outbox (#1453)."""

    dependencies = [
        ("engine", "0024_widen_subnetallocation_vpc_id"),
    ]

    operations = [
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
