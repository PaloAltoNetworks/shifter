"""Effective-privilege proof for the subnet coordination cutover (#1838).

A migration emitting REVOKE strings is not evidence; effective privilege is, and
for this phase the grant posture *is* the API: the provisioner may call three
routines and may not touch the table behind them. So this suite proves both
directions, and proves the strongest form by executing as the role rather than
by reading a catalog -- an inherited, PUBLIC, or default privilege would satisfy
a catalog lookup that a real call still fails.

Two-sided on purpose: the capability this cutover removed must be gone, and the
grants the still-uncut families depend on must survive, so an over-broad revoke
fails here rather than in production.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from engine.models import OperationInput, Range, Request

_WORKSPACE_ID = 1
_NETWORK_ID = "range-network-test"

_RESERVE_SIGNATURE = "public.engine_reserve_subnet_cidrs(text,uuid,uuid,text,cidr,integer,integer,cidr[],text)"
_READ_SIGNATURE = "public.engine_read_subnet_reservation(text,uuid,uuid)"
_RELEASE_SIGNATURE = "public.engine_release_subnet_reservation(text,uuid,uuid)"
_SIGNATURES = (_RESERVE_SIGNATURE, _READ_SIGNATURE, _RELEASE_SIGNATURE)

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def _scalar(sql: str, params: list) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


def _table(table: str, priv: str) -> bool:
    return bool(_scalar("SELECT has_table_privilege('provisioner_lambda', %s, %s)", [table, priv]))


def _sequence(sequence: str, priv: str) -> bool:
    return bool(_scalar("SELECT has_sequence_privilege('provisioner_lambda', %s, %s)", [sequence, priv]))


def _column(table: str, column: str, priv: str) -> bool:
    return bool(_scalar("SELECT has_column_privilege('provisioner_lambda', %s, %s, %s)", [table, column, priv]))


def _function(role: str, signature: str) -> bool:
    return bool(_scalar("SELECT has_function_privilege(%s, %s, 'EXECUTE')", [role, signature]))


class TestAllocationTableCapabilityIsGone:
    @pytest.mark.parametrize("priv", ["SELECT", "INSERT", "UPDATE", "DELETE"])
    def test_direct_table_access_is_revoked(self, priv):
        assert _table("engine_subnetallocation", priv) is False

    @pytest.mark.parametrize("priv", ["USAGE", "SELECT"])
    def test_sequence_access_is_revoked(self, priv):
        # Without the sequence the role could not INSERT even if the table grant
        # came back by another route.
        assert _sequence("engine_subnetallocation_id_seq", priv) is False

    def test_range_config_write_is_revoked(self):
        # The provisioner no longer mutates authored intent with realized CIDRs
        # (ADR-043-R6), so the column grant from mission_control 0038 goes.
        assert _column("mission_control_range", "range_config", "UPDATE") is False


class TestCoordinationRoutinesAreTheOnlyWayIn:
    @pytest.mark.parametrize("signature", _SIGNATURES)
    def test_the_provisioner_may_execute_each_routine(self, signature):
        assert _function("provisioner_lambda", signature) is True

    @pytest.mark.parametrize("signature", _SIGNATURES)
    def test_public_may_not_execute_any_routine(self, signature):
        # Functions are EXECUTE-to-PUBLIC by default; without the REVOKE the
        # narrow GRANT would be decoration.
        assert _function("public", signature) is False

    @pytest.mark.parametrize("signature", _SIGNATURES)
    def test_each_routine_is_security_definer_with_a_fixed_search_path(self, signature):
        row = _scalar(
            "SELECT ARRAY[p.prosecdef::text, COALESCE(array_to_string(p.proconfig, ','), '')] "
            "FROM pg_proc p WHERE p.oid = %s::regprocedure",
            [signature],
        )
        secdef, proconfig = row[0], row[1]

        assert secdef == "true"
        # A SECURITY DEFINER routine without a pinned search_path is the classic
        # privilege-escalation shape: the caller chooses which schema's objects
        # the definer's rights are applied to.
        assert "search_path=" in proconfig.replace(" ", "")

    @pytest.mark.parametrize("signature", _SIGNATURES)
    def test_no_routine_is_owned_by_the_calling_role(self, signature):
        owner = _scalar(
            "SELECT pg_get_userbyid(p.proowner) FROM pg_proc p WHERE p.oid = %s::regprocedure",
            [signature],
        )

        # Ownership would let the caller redefine the very routine that fences it.
        assert owner != "provisioner_lambda"


class TestGrantsTheUncutFamiliesStillNeed:
    def test_shared_domain_reads_survive(self):
        # Cyberscript range provision/destroy and the NGFW lookups still read
        # these; they belong to the residual teardown (#1839), not this phase.
        assert _table("mission_control_range", "SELECT") is True
        assert _table("engine_request", "SELECT") is True
        assert _table("engine_instance", "SELECT") is True

    def test_the_operation_boundary_still_works(self):
        assert _table("engine_operation_input", "SELECT") is True
        assert _table("engine_operation_result_inbox", "INSERT") is True

    def test_other_range_column_writes_survive(self):
        # write_provisioned_state still writes this column; only range_config went.
        assert _column("mission_control_range", "ngfw_instance_id", "UPDATE") is True


class TestExecutingAsTheProvisionerRole:
    """Prove the posture by acting as the role, not by reading its catalog rows."""

    def _seed_range(self) -> tuple[str, str]:
        from shared.operation_envelope import build_operation_envelope

        operation_id = uuid4()
        request_id = uuid4()
        user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
        request = Request.objects.create(request_id=request_id, request_type="range", user=user)
        Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=request,
            user=user,
            status=Range.Status.PROVISIONING,
            provisioner_operation_id=operation_id,
        )
        envelope = build_operation_envelope(
            operation_id=operation_id,
            request_id=request_id,
            resource="range",
            operation="provision",
            payload={"range_spec": {}},
        )
        OperationInput.objects.create(
            operation_id=operation_id,
            request_id=request_id,
            resource="range",
            operation="provision",
            contract_version=envelope["contract_version"],
            envelope=envelope,
        )
        return str(operation_id), str(request_id)

    def test_the_role_can_reserve_through_the_routine_but_not_read_the_table(self):
        from django.db.utils import ProgrammingError

        operation_id, request_id = self._seed_range()

        with connection.cursor() as cursor:
            cursor.execute("SET ROLE provisioner_lambda")
            try:
                cursor.execute(
                    "SELECT ordinal, subnet_cidr FROM engine_reserve_subnet_cidrs("
                    "%s, %s::uuid, %s::uuid, %s, %s::cidr, %s, %s, %s::cidr[], %s)",
                    ["1", operation_id, request_id, _NETWORK_ID, "10.1.0.0/16", 28, 1, "{}", "sha256:" + "0" * 64],
                )
                reserved = cursor.fetchall()
                assert len(reserved) == 1

                # The same role, the same connection, one statement later: the
                # table the routine just wrote is unreachable directly.
                with pytest.raises(ProgrammingError):
                    cursor.execute("SELECT cidr FROM engine_subnetallocation")
            finally:
                # The failed statement aborted the transaction, so RESET ROLE has
                # to happen on a clean one.
                connection.rollback()
                with connection.cursor() as reset:
                    reset.execute("RESET ROLE")

    def test_the_role_cannot_insert_into_the_allocation_table(self):
        from django.db.utils import ProgrammingError

        with connection.cursor() as cursor:
            cursor.execute("SET ROLE provisioner_lambda")
            try:
                with pytest.raises(ProgrammingError):
                    cursor.execute(
                        "INSERT INTO engine_subnetallocation "
                        "(vpc_id, cidr, subnet_size, range_id, request_id, created_at) "
                        "VALUES ('vpc-x', '10.1.9.0/28', 28, 0, '', NOW())"
                    )
            finally:
                connection.rollback()
                with connection.cursor() as reset:
                    reset.execute("RESET ROLE")

    def test_the_role_cannot_update_range_config(self):
        from django.db.utils import ProgrammingError

        with connection.cursor() as cursor:
            cursor.execute("SET ROLE provisioner_lambda")
            try:
                with pytest.raises(ProgrammingError):
                    cursor.execute("UPDATE mission_control_range SET range_config = '{}'::jsonb")
            finally:
                connection.rollback()
                with connection.cursor() as reset:
                    reset.execute("RESET ROLE")
