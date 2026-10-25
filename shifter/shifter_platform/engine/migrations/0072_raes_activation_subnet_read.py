"""Permit current RAES activation generations to read owned subnet reservations."""

from importlib import import_module

from django.db import migrations

_coordination = import_module("engine.migrations.0046_subnet_reservation_coordination")

_RANGE_RESOURCE_PREDICATE = "AND i.resource = 'range';"
_RAES_RESOURCE_PREDICATE = "AND i.resource IN ('range', 'raes-range');"
_OPERATION_DECLARATION = "    v_operation text;"
_OPERATION_AND_RESOURCE_DECLARATION = "    v_operation text;\n    v_resource text;"
_SELECT_OPERATION = "    SELECT i.operation\n      INTO v_operation"
_SELECT_OPERATION_AND_RESOURCE = "    SELECT i.operation, i.resource\n      INTO v_operation, v_resource"
_READ_OPERATIONS = "IF v_operation NOT IN ('provision', 'destroy') THEN"
_READ_OPERATIONS_WITH_ACTIVATION = """IF v_operation NOT IN ('provision', 'destroy', 'activate')
       OR (v_operation = 'activate' AND v_resource <> 'raes-range') THEN"""


def _replace_once(sql: str, old: str, new: str) -> str:
    """Replace one reviewed fragment and fail if the inherited routine drifted."""
    if sql.count(old) != 1:
        raise RuntimeError("subnet coordination read routine changed unexpectedly")
    return sql.replace(old, new)


def _read_function(*, activation: bool) -> str:
    """Render the RAES-aware read routine with the requested operation policy."""
    sql = _replace_once(_coordination._READ_FUNCTION, _RANGE_RESOURCE_PREDICATE, _RAES_RESOURCE_PREDICATE)
    if activation:
        sql = _replace_once(sql, _OPERATION_DECLARATION, _OPERATION_AND_RESOURCE_DECLARATION)
        sql = _replace_once(sql, _SELECT_OPERATION, _SELECT_OPERATION_AND_RESOURCE)
        sql = _replace_once(sql, _READ_OPERATIONS, _READ_OPERATIONS_WITH_ACTIVATION)
    return sql


def _install(apps, schema_editor, *, activation: bool) -> None:
    """Replace only the read routine while preserving its hardened grants."""
    if not _coordination._is_postgres(schema_editor):
        return
    schema_editor.execute(_read_function(activation=activation))
    if _coordination._role_exists(schema_editor):
        schema_editor.execute(_coordination._HARDEN_AND_GRANT)
        schema_editor.execute(_coordination._REVOKE_TABLE_ACCESS)
    else:
        schema_editor.execute(
            "\n".join(
                line for line in _coordination._HARDEN_AND_GRANT.splitlines() if not line.strip().startswith("GRANT")
            )
        )


def allow_raes_activation_read(apps, schema_editor) -> None:
    """Allow current RAES activation generations to recover their owned projection."""
    _install(apps, schema_editor, activation=True)


def restore_provision_destroy_read(apps, schema_editor) -> None:
    """Restore the prior RAES provision/destroy-only read policy."""
    _install(apps, schema_editor, activation=False)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0071_model_workload_budgets"),
    ]

    operations = [
        migrations.RunPython(allow_raes_activation_read, restore_provision_destroy_read),
    ]
