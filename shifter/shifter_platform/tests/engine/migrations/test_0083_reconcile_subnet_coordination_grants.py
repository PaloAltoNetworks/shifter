"""Tests for the provisioner capability-role reconciliation migration."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

MIGRATION = importlib.import_module("engine.migrations.0083_reconcile_subnet_coordination_grants")


def _schema_editor(*, vendor: str, runtime_role_exists: bool):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchone.return_value = (1,) if runtime_role_exists else None
    connection = SimpleNamespace(vendor=vendor, cursor=MagicMock(return_value=cursor))
    return SimpleNamespace(connection=connection, execute=MagicMock()), cursor


def test_postgresql_grants_capability_role_to_dedicated_runtime_login() -> None:
    schema_editor, cursor = _schema_editor(vendor="postgresql", runtime_role_exists=True)

    MIGRATION.reconcile_subnet_coordination_grants(None, schema_editor)

    assert schema_editor.execute.call_args_list[0].args == (MIGRATION._RECONCILE_GRANTS,)
    assert schema_editor.execute.call_args_list[1].args == ("GRANT provisioner_lambda TO provisioner_runtime;",)
    cursor.execute.assert_called_once_with("SELECT 1 FROM pg_roles WHERE rolname = %s", ["provisioner_runtime"])


def test_postgresql_skips_membership_until_terraform_creates_runtime_login() -> None:
    schema_editor, _cursor = _schema_editor(vendor="postgresql", runtime_role_exists=False)

    MIGRATION.reconcile_subnet_coordination_grants(None, schema_editor)

    schema_editor.execute.assert_called_once_with(MIGRATION._RECONCILE_GRANTS)


def test_non_postgresql_database_is_unchanged() -> None:
    schema_editor, cursor = _schema_editor(vendor="sqlite", runtime_role_exists=True)

    MIGRATION.reconcile_subnet_coordination_grants(None, schema_editor)

    schema_editor.execute.assert_not_called()
    cursor.execute.assert_not_called()
