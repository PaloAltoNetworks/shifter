"""Effective-privilege proof for the provisioner phase-7 allowlist (#1839).

A migration emitting REVOKE strings is not evidence; effective privilege is. This
suite is the enforcing gate for ADR-043-R1 at the cyberscript cutover boundary:
every named allowlist entry must be present, and every other domain-table
privilege for ``provisioner_lambda`` must be denied.

Two-sided on purpose: an over-broad revoke fails here rather than in production,
and a stale grant outside the allowlist fails here rather than silently widening
the boundary.
"""

from __future__ import annotations

import pytest
from django.db import connection

_ROLE = "provisioner_lambda"

_RESERVE_SIGNATURE = "public.engine_reserve_subnet_cidrs(text,uuid,uuid,text,cidr,integer,integer,cidr[],text)"
_READ_SIGNATURE = "public.engine_read_subnet_reservation(text,uuid,uuid)"
_RELEASE_SIGNATURE = "public.engine_release_subnet_reservation(text,uuid,uuid)"
_COORDINATION_SIGNATURES = (_RESERVE_SIGNATURE, _READ_SIGNATURE, _RELEASE_SIGNATURE)

# Live writers on the surviving cyberscript provision/destroy path (#1836 snapshot,
# updated for #1838 range_config revoke).
_ALLOWED_RANGE_UPDATE_COLUMNS = frozenset(
    {
        "status",
        "error_message",
        "paused_at",
        "ready_at",
        "updated_at",
        "provisioned_instances",
        "vpn_access_binding",
        "ngfw_instance_id",
        "destroyed_at",
    }
)

# Tables the role may touch at all after phase 7. Everything else must read as
# denied through effective-privilege checks.
_ALLOWED_TABLE_PRIVILEGES: dict[str, frozenset[str]] = {
    "engine_instance": frozenset({"SELECT", "UPDATE"}),
    "engine_subnet": frozenset({"UPDATE"}),
    "engine_app": frozenset({"SELECT"}),
    "engine_request": frozenset({"SELECT"}),
    "engine_operation_input": frozenset({"SELECT"}),
    "engine_operation_result_inbox": frozenset({"INSERT"}),
    "mission_control_range": frozenset({"SELECT", "UPDATE"}),
}

pytestmark = [pytest.mark.postgres, pytest.mark.django_db]


def _scalar(sql: str, params: list | None = None) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        return row[0] if row else None


def _table(table: str, priv: str) -> bool:
    return bool(_scalar("SELECT has_table_privilege(%s, %s, %s)", [_ROLE, table, priv]))


def _column(table: str, column: str, priv: str) -> bool:
    return bool(
        _scalar(
            "SELECT has_column_privilege(%s, %s, %s, %s)",
            [_ROLE, table, column, priv],
        )
    )


def _sequence(sequence: str, priv: str) -> bool:
    qualified = f"public.{sequence}"
    return bool(_scalar("SELECT has_sequence_privilege(%s, %s, %s)", [_ROLE, qualified, priv]))


def _function(signature: str) -> bool:
    return bool(_scalar("SELECT has_function_privilege(%s, %s, 'EXECUTE')", [_ROLE, signature]))


def _range_update_columns_with_priv(priv: str) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'mission_control_range'
            ORDER BY column_name
            """
        )
        columns = [row[0] for row in cursor.fetchall()]
    return {column for column in columns if _column("mission_control_range", column, priv)}


class TestOutboxAndLegacyCapabilitiesAreGone:
    @pytest.mark.parametrize("priv", ["SELECT", "INSERT", "UPDATE", "DELETE"])
    def test_outbox_table_access_is_revoked(self, priv):
        assert _table("engine_range_event_outbox", priv) is False

    @pytest.mark.parametrize("priv", ["USAGE", "SELECT"])
    def test_outbox_sequence_access_is_revoked(self, priv):
        assert _sequence("engine_range_event_outbox_id_seq", priv) is False

    def test_engine_app_update_is_revoked(self):
        assert _table("engine_app", "UPDATE") is False

    def test_range_config_update_is_revoked(self):
        # ADR-043-R6 / #1838: authored intent is no longer mutated by the provisioner.
        assert _column("mission_control_range", "range_config", "UPDATE") is False

    def test_gwlb_endpoint_update_is_revoked(self):
        assert _column("mission_control_range", "gwlb_endpoint_id", "UPDATE") is False

    @pytest.mark.parametrize("priv", ["SELECT", "INSERT", "UPDATE", "DELETE"])
    def test_subnet_allocation_direct_access_is_revoked(self, priv):
        assert _table("engine_subnetallocation", priv) is False

    @pytest.mark.parametrize("priv", ["USAGE", "SELECT"])
    def test_subnet_allocation_sequence_access_is_revoked(self, priv):
        assert _sequence("engine_subnetallocation_id_seq", priv) is False

    def test_raes_delivery_binding_read_is_revoked(self):
        assert _table("engine_raes_content_delivery_binding", "SELECT") is False


class TestAllowlistedTablePrivileges:
    @pytest.mark.parametrize(
        ("table", "priv"),
        [
            ("engine_instance", "UPDATE"),
            ("engine_subnet", "UPDATE"),
            ("engine_request", "SELECT"),
            ("engine_instance", "SELECT"),
            ("engine_app", "SELECT"),
            ("engine_operation_input", "SELECT"),
            ("engine_operation_result_inbox", "INSERT"),
            ("mission_control_range", "SELECT"),
        ],
    )
    def test_required_privilege_is_present(self, table, priv):
        assert _table(table, priv) is True

    def test_inbox_reads_and_mutations_stay_denied(self):
        assert _table("engine_operation_result_inbox", "SELECT") is False
        assert _table("engine_operation_result_inbox", "UPDATE") is False
        assert _table("engine_operation_result_inbox", "DELETE") is False

    def test_operation_input_writes_stay_denied(self):
        assert _table("engine_operation_input", "INSERT") is False
        assert _table("engine_operation_input", "UPDATE") is False

    def test_engine_subnet_select_is_revoked(self):
        # Only UPDATE survives on engine_subnet; there is no live SELECT writer.
        assert _table("engine_subnet", "SELECT") is False

    @pytest.mark.parametrize("column", sorted(_ALLOWED_RANGE_UPDATE_COLUMNS))
    def test_allowlisted_range_column_updates_survive(self, column):
        assert _column("mission_control_range", column, "UPDATE") is True

    def test_no_other_range_column_updates_survive(self):
        granted = _range_update_columns_with_priv("UPDATE")
        assert granted == set(_ALLOWED_RANGE_UPDATE_COLUMNS)


class TestCoordinationRoutinesFromPhase6:
    @pytest.mark.parametrize("signature", _COORDINATION_SIGNATURES)
    def test_provisioner_may_execute_each_routine(self, signature):
        assert _function(signature) is True


class TestNoUnexpectedDomainTablePrivileges:
    _DOMAIN_TABLE_PREFIXES = ("engine_", "mission_control_")
    _TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

    def test_only_allowlisted_table_privileges_remain(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                  AND (table_name LIKE %s OR table_name LIKE %s)
                ORDER BY table_name
                """,
                ["engine\\_%", "mission_control\\_%"],
            )
            tables = [row[0] for row in cursor.fetchall()]

        # Effective privilege, not catalog grantee rows: inherited/PUBLIC grants
        # must fail the closed allowlist the same way direct grants do.
        unexpected = []
        for table in tables:
            for priv in self._TABLE_PRIVILEGES:
                if not _table(table, priv):
                    continue
                allowed = _ALLOWED_TABLE_PRIVILEGES.get(table)
                if allowed is None or priv not in allowed:
                    unexpected.append((table, priv))

        assert unexpected == []
