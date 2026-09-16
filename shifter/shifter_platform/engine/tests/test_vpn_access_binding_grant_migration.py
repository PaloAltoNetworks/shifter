from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

MIGRATION = import_module("engine.migrations.0034_grant_vpn_access_binding_to_provisioner")


def _schema_editor(vendor: str):
    return SimpleNamespace(connection=SimpleNamespace(vendor=vendor), execute=Mock())


def test_postgres_migration_grants_only_vpn_access_binding_update():
    schema_editor = _schema_editor("postgresql")

    MIGRATION.grant_vpn_access_binding(None, schema_editor)

    schema_editor.execute.assert_called_once_with(
        "GRANT UPDATE (vpn_access_binding) ON mission_control_range TO provisioner_lambda;"
    )


def test_postgres_reverse_revokes_only_vpn_access_binding_update():
    schema_editor = _schema_editor("postgresql")

    MIGRATION.revoke_vpn_access_binding(None, schema_editor)

    schema_editor.execute.assert_called_once_with(
        "REVOKE UPDATE (vpn_access_binding) ON mission_control_range FROM provisioner_lambda;"
    )


def test_non_postgres_migration_is_a_noop():
    schema_editor = _schema_editor("sqlite")

    MIGRATION.grant_vpn_access_binding(None, schema_editor)
    MIGRATION.revoke_vpn_access_binding(None, schema_editor)

    schema_editor.execute.assert_not_called()
