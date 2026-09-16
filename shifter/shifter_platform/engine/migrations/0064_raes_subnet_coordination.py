"""Authorize RAES range generations at the shared subnet coordination boundary."""

from importlib import import_module

from django.db import migrations

_coordination = import_module("engine.migrations.0046_subnet_reservation_coordination")


def _with_raes_range(sql: str) -> str:
    """Extend the existing range-operation predicate without changing its policy."""
    original = "AND i.resource = 'range';"
    replacement = "AND i.resource IN ('range', 'raes-range');"
    if sql.count(original) != 1:
        raise RuntimeError("subnet coordination resource predicate changed unexpectedly")
    return sql.replace(original, replacement)


def _install(apps, schema_editor, *, raes_range: bool) -> None:
    """Replace all three routines while preserving their grants and table boundary."""
    if not _coordination._is_postgres(schema_editor):
        return
    transform = _with_raes_range if raes_range else lambda sql: sql
    schema_editor.execute(transform(_coordination._RESERVE_FUNCTION))
    schema_editor.execute(transform(_coordination._READ_FUNCTION))
    schema_editor.execute(transform(_coordination._RELEASE_FUNCTION))
    if _coordination._role_exists(schema_editor):
        schema_editor.execute(_coordination._HARDEN_AND_GRANT)
        schema_editor.execute(_coordination._REVOKE_TABLE_ACCESS)
    else:
        schema_editor.execute(
            "\n".join(
                line
                for line in _coordination._HARDEN_AND_GRANT.splitlines()
                if not line.strip().startswith("GRANT")
            )
        )


def allow_raes_range(apps, schema_editor):
    """Let canonical ``raes-range`` provision/destroy generations coordinate CIDRs."""
    _install(apps, schema_editor, raes_range=True)


def restore_legacy_range_only(apps, schema_editor):
    """Restore the original Cyberscript-only operation predicate on rollback."""
    _install(apps, schema_editor, raes_range=False)


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0063_preparationgrant_installation_and_more"),
    ]

    operations = [
        migrations.RunPython(allow_raes_range, restore_legacy_range_only),
    ]
