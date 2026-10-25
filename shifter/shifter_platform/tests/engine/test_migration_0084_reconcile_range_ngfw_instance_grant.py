"""Regression tests for the range-to-NGFW grant reconciliation."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

MIGRATION = importlib.import_module("engine.migrations.0084_reconcile_range_ngfw_instance_grant")


def _schema_editor(*, vendor: str = "postgresql", role_exists: bool = True, column_exists: bool = True):
    role_cursor = MagicMock()
    role_cursor.__enter__.return_value = role_cursor
    role_cursor.fetchone.return_value = (1,) if role_exists else None
    column_cursor = MagicMock()
    column_cursor.__enter__.return_value = column_cursor
    column_cursor.fetchone.return_value = (1,) if column_exists else None
    connection = SimpleNamespace(vendor=vendor, cursor=MagicMock(side_effect=[role_cursor, column_cursor]))
    return SimpleNamespace(connection=connection, execute=MagicMock())


def test_grant_restores_only_the_range_ngfw_instance_column() -> None:
    schema_editor = _schema_editor()

    MIGRATION.grant_range_ngfw_instance_update(None, schema_editor)

    schema_editor.execute.assert_called_once_with(
        "GRANT UPDATE (ngfw_instance_id) ON mission_control_range TO provisioner_lambda;"
    )


def test_grant_skips_a_schema_without_the_column() -> None:
    schema_editor = _schema_editor(column_exists=False)

    MIGRATION.grant_range_ngfw_instance_update(None, schema_editor)

    schema_editor.execute.assert_not_called()


def test_reverse_revokes_only_the_range_ngfw_instance_column() -> None:
    schema_editor = _schema_editor()

    MIGRATION.revoke_range_ngfw_instance_update(None, schema_editor)

    schema_editor.execute.assert_called_once_with(
        "REVOKE UPDATE (ngfw_instance_id) ON mission_control_range FROM provisioner_lambda;"
    )
