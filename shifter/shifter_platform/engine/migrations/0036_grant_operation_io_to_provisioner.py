# Grant provisioner_lambda the minimal operation-boundary privileges (#1834).
#
# ADR-043 Phase 2 (shadow): the provisioner reads its immutable input by
# operation_id and appends versioned results to the inbox. It needs only:
#   - SELECT on engine_operation_input (read the input projection), and
#   - INSERT on engine_operation_result_inbox + USAGE on its id sequence
#     (append-only result writes).
# It gets no UPDATE/DELETE on either table and no access to domain tables here;
# the engine-owned applier reads/updates the inbox under the portal runtime role.
# Forward-only, additive: this migration does not revoke any legacy grant
# (grant teardown is a later #478 phase).

from django.db import migrations


def grant_permissions(apps, schema_editor):
    """Grant provisioner_lambda input SELECT + inbox INSERT/sequence USAGE."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        GRANT SELECT ON engine_operation_input TO provisioner_lambda;
        GRANT INSERT ON engine_operation_result_inbox TO provisioner_lambda;
        GRANT USAGE ON SEQUENCE engine_operation_result_inbox_id_seq TO provisioner_lambda;
        """
    )


def revoke_permissions(apps, schema_editor):
    """Revoke provisioner_lambda access to the operation-boundary tables."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        REVOKE SELECT ON engine_operation_input FROM provisioner_lambda;
        REVOKE INSERT ON engine_operation_result_inbox FROM provisioner_lambda;
        REVOKE USAGE ON SEQUENCE engine_operation_result_inbox_id_seq FROM provisioner_lambda;
        """
    )


class Migration(migrations.Migration):
    """Grant provisioner_lambda operation input read + result inbox append (#1834)."""

    dependencies = [
        ("engine", "0035_operation_input_result_inbox"),
    ]

    operations = [
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
