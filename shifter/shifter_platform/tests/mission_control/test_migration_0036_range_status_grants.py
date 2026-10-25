"""Regression tests for the historical range-status grant migration."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

MIGRATION = importlib.import_module("mission_control.migrations.0036_grant_range_status_to_provisioner")


def _schema_editor(columns: list[str]):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = [(column,) for column in columns]
    connection = SimpleNamespace(vendor="postgresql", cursor=MagicMock(return_value=cursor))
    return SimpleNamespace(connection=connection, execute=MagicMock())


def test_grant_uses_only_columns_that_survive_the_historical_graph() -> None:
    schema_editor = _schema_editor(["updated_at", "status", "error_message"])

    MIGRATION.grant_range_status_permissions(None, schema_editor)

    schema_editor.execute.assert_called_once_with(
        "GRANT UPDATE (error_message, status, updated_at) ON mission_control_range TO provisioner_lambda;"
    )


def test_grant_is_noop_when_no_legacy_column_survives() -> None:
    schema_editor = _schema_editor([])

    MIGRATION.grant_range_status_permissions(None, schema_editor)

    schema_editor.execute.assert_not_called()
