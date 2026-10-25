"""Reconcile provisioner access to the subnet coordination routines.

The coordination functions can be installed before the cross-app migration that
creates ``provisioner_lambda``.  In that ordering the original conditional grant
is skipped permanently, leaving the provisioner unable to reserve, read, or
release range subnets.  This migration runs after both migration branches and
restates the already-reviewed narrow function boundary.
"""

from django.db import migrations

_RECONCILE_GRANTS = """
REVOKE ALL ON FUNCTION public.engine_reserve_subnet_cidrs(
    text, uuid, uuid, text, cidr, integer, integer, cidr[], text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.engine_read_subnet_reservation(text, uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.engine_release_subnet_reservation(text, uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.engine_reserve_subnet_cidrs(
    text, uuid, uuid, text, cidr, integer, integer, cidr[], text) TO provisioner_lambda;
GRANT EXECUTE ON FUNCTION public.engine_read_subnet_reservation(text, uuid, uuid) TO provisioner_lambda;
GRANT EXECUTE ON FUNCTION public.engine_release_subnet_reservation(text, uuid, uuid) TO provisioner_lambda;
"""


def reconcile_subnet_coordination_grants(apps, schema_editor) -> None:
    """Restore the intended function-only provisioner capability on PostgreSQL."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(_RECONCILE_GRANTS)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", ["provisioner_runtime"])
        provisioner_runtime_exists = cursor.fetchone() is not None
    if provisioner_runtime_exists:
        schema_editor.execute("GRANT provisioner_lambda TO provisioner_runtime;")


class Migration(migrations.Migration):
    """Run the grant only after the provisioner role and functions both exist."""

    dependencies = [
        ("engine", "0082_model_policy_transition"),
        ("mission_control", "0044_revoke_residual_grants_from_provisioner"),
    ]

    operations = [
        # The earlier migrations define this as the durable privilege contract.
        # Rolling this ordering repair back must not revoke that contract.
        migrations.RunPython(reconcile_subnet_coordination_grants, migrations.RunPython.noop),
    ]
