# Revoke the provisioner's ACES read capability (ADR-043 phase 5, #1837).
#
# Both ACES inputs now arrive on the immutable operation-input projection,
# materialized by engine.launch_intents in the launch-intent transaction and
# selected by the provisioner via its canonical operation_id:
#   - content-delivery bindings  aces_range_ops -> AcesOperationInput.delivery_bindings
#   - image registry candidates  aces_range_ops -> AcesOperationInput.image_candidates_for
# The provisioner-side readers (provisioner_db_aces.py) are deleted, not merely
# unused, so nothing can regress onto the table.
#
# Deliberately narrow. Migration 0031 granted SELECT on the binding table for
# the ACES realization path alone, so revoking it here cannot break another
# family. Everything else the ACES path used to read is shared:
#   - mission_control_range / engine_request SELECT: still read by the uncut
#     cyberscript range family (provisioner_db.get_range_data_by_request_id).
#   - engine_instance SELECT: still read by NGFW lookups and cyberscript.
#     Phase 5 removes range_backend_evidence's use of it, but not the last use.
# Those belong to the residual teardown (#1839), after the remaining families
# cut over. Migrations 0012/0031 are evidence of the old capability, not edit
# targets (ADR-043: forward migrations only).
#
# engine_aces_image_mapping is deliberately absent from the REVOKE below: it was
# never granted to provisioner_lambda in the first place (migration 0027 creates
# the table with no GRANT), so the direct read the provisioner used to issue
# would have failed under real grants. Naming an un-granted object in a REVOKE
# is harmless in PostgreSQL, but asserting the absence is the real control --
# TestPhase5EffectivePrivileges proves it, including privileges that could be
# inherited from a role or applied outside the model-creation migration.

from django.db import migrations

_ROLE = "provisioner_lambda"

# Both grant statements are written as literals rather than interpolated from
# constants. The table and role are fixed at authoring time, so interpolation
# buys nothing and builds a `SELECT ... FROM ...` shape out of string pieces --
# which is both the thing B608 exists to catch and a pattern a later edit could
# turn into a real one. Identifiers cannot be bound as parameters in DDL, so a
# literal is the only construction here with no dynamic input at all.
_REVOKE_BINDING_READ = "REVOKE SELECT ON engine_aces_content_delivery_binding FROM provisioner_lambda;"
_GRANT_BINDING_READ = "GRANT SELECT ON engine_aces_content_delivery_binding TO provisioner_lambda;"


def _role_exists(schema_editor) -> bool:
    """Return True when the database role exists (absent in some local setups)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [_ROLE])
        return cursor.fetchone() is not None


def _applies(schema_editor) -> bool:
    """Return True when this is a PostgreSQL database carrying the role."""
    return schema_editor.connection.vendor == "postgresql" and _role_exists(schema_editor)


def revoke_aces_binding_read(apps, schema_editor):
    """Revoke SELECT on the ACES delivery-binding table from provisioner_lambda."""
    if not _applies(schema_editor):
        return
    schema_editor.execute(_REVOKE_BINDING_READ)


def grant_aces_binding_read(apps, schema_editor):
    """Restore SELECT on the ACES delivery-binding table to provisioner_lambda."""
    if not _applies(schema_editor):
        return
    schema_editor.execute(_GRANT_BINDING_READ)


class Migration(migrations.Migration):
    """Revoke the ACES family's domain-table read capability from the provisioner."""

    dependencies = [
        ("engine", "0044_capacity_budget_draws"),
    ]

    operations = [
        migrations.RunPython(revoke_aces_binding_read, grant_aces_binding_read),
    ]
