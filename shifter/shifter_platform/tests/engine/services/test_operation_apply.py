"""Tests for the Engine-owned operation-result applier (ADR-043).

The applier authoritatively applies declared operation families and records
validation-only dispositions for compatibility families. Logic tests run on any
backend; the concurrency (skip_locked) and effective-privilege (real GRANTs)
tests require PostgreSQL and are marked accordingly.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from engine.models import (
    Instance,
    OperationResultDisposition,
    OperationResultInbox,
    OperationResultKind,
    Range,
    RangeEventOutbox,
    Request,
)
from engine.services import apply_pending_operation_results, evaluate_operation_result
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db


def test_applier_descriptions_reflect_authoritative_cutovers():
    """Public worker descriptions must not present every result as shadow-only."""
    from engine.management.commands.apply_operation_results import Command
    from engine.models import _operation_io
    from engine.services import _operation_apply

    descriptions = (
        _operation_io.__doc__ or "",
        _operation_apply.__doc__ or "",
        _operation_apply.apply_pending_operation_results.__doc__ or "",
    )

    assert all("sole authoritative writer" not in description for description in descriptions)
    assert all("never mutates domain state" not in description for description in descriptions)
    assert all("authoritative" in description.lower() for description in descriptions)
    assert "shadow" not in Command.help.lower()


def _seed(
    *,
    resource: str = "range",
    operation: str = "provision",
    result_kind: str = OperationResultKind.TERMINAL_SUCCESS,
    payload: dict | None = None,
    current: bool = True,
    request_matches: bool = True,
    contract_version: str = "1",
    corrupt_digest: bool = False,
    envelope_override: dict | None = None,
) -> OperationResultInbox:
    """Seed a Range (owning the current generation unless ``current`` is False)
    and a matching inbox result row, returning the row."""
    payload = payload if payload is not None else {"status": "ready"}
    operation_id = uuid4()
    request_id = uuid4()
    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="range", user=user)
    Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=Range.Status.PROVISIONING,
        provisioner_operation_id=operation_id if current else uuid4(),
    )
    envelope_request_id = request_id if request_matches else uuid4()
    envelope = envelope_override or build_operation_envelope(
        operation_id=operation_id,
        request_id=envelope_request_id,
        resource=resource,
        operation=operation,
        payload=payload,
    )
    digest = "sha256:" + "0" * 64 if corrupt_digest else canonical_payload_digest(envelope.get("payload", {}))
    return OperationResultInbox.objects.create(
        operation_id=operation_id,
        request_id=envelope_request_id,
        resource=resource,
        operation=operation,
        contract_version=contract_version,
        result_kind=result_kind,
        result_identity=f"{operation_id}:{result_kind}",
        payload_digest=digest,
        envelope=envelope,
    )


class TestEvaluateOperationResult:
    def test_validated_when_generation_current_and_owned(self):
        assert evaluate_operation_result(_seed())[0] == OperationResultDisposition.VALIDATED

    def test_rejected_stale_when_generation_rotated(self):
        disposition, detail = evaluate_operation_result(_seed(current=False))
        assert disposition == OperationResultDisposition.REJECTED_STALE
        assert "generation" in detail

    def test_rejected_ownership_when_request_mismatches(self):
        disposition, _ = evaluate_operation_result(_seed(request_matches=False))
        assert disposition == OperationResultDisposition.REJECTED_OWNERSHIP

    def test_rejected_version_for_unsupported_contract_version(self):
        assert (
            evaluate_operation_result(_seed(contract_version="999"))[0] == OperationResultDisposition.REJECTED_VERSION
        )

    def test_rejected_conflict_on_digest_mismatch(self):
        assert evaluate_operation_result(_seed(corrupt_digest=True))[0] == OperationResultDisposition.REJECTED_CONFLICT

    def test_rejected_invalid_on_malformed_envelope(self):
        row = _seed(envelope_override={"contract_version": "1", "operation_id": "not-a-uuid"})
        assert evaluate_operation_result(row)[0] == OperationResultDisposition.REJECTED_INVALID


def _seed_ngfw(*, current: bool = True, request_matches: bool = True) -> OperationResultInbox:
    """Seed an NGFW Instance (the third closed resource kind) owning the current
    generation unless ``current`` is False, plus a matching inbox result row, so
    the ``resource == "ngfw"`` target-resolution branch is fenced like range."""
    payload = {"status": "ready"}
    operation_id = uuid4()
    request_id = uuid4()
    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="ngfw", user=user)
    Instance.objects.create(
        request=request,
        role=Instance.Role.NGFW,
        os_type=Instance.OSType.PANOS,
        status="provisioning",
        provisioner_operation_id=operation_id if current else uuid4(),
    )
    envelope_request_id = request_id if request_matches else uuid4()
    envelope = build_operation_envelope(
        operation_id=operation_id,
        request_id=envelope_request_id,
        resource="ngfw",
        operation="provision",
        payload=payload,
    )
    return OperationResultInbox.objects.create(
        operation_id=operation_id,
        request_id=envelope_request_id,
        resource="ngfw",
        operation="provision",
        contract_version="1",
        result_kind=OperationResultKind.RESOURCE_STATE,
        result_identity=f"{operation_id}:{OperationResultKind.RESOURCE_STATE}",
        payload_digest=canonical_payload_digest(payload),
        envelope=envelope,
    )


class TestEvaluateNgfwOperationResult:
    """The ngfw branch of _resolve_operation_target (Instance filtered by
    role=NGFW) must be generation/ownership-fenced exactly like range."""

    def test_validated_when_ngfw_generation_current_and_owned(self):
        assert evaluate_operation_result(_seed_ngfw())[0] == OperationResultDisposition.VALIDATED

    def test_rejected_stale_when_ngfw_generation_rotated(self):
        assert evaluate_operation_result(_seed_ngfw(current=False))[0] == OperationResultDisposition.REJECTED_STALE

    def test_rejected_ownership_when_ngfw_request_mismatches(self):
        disposition, _ = evaluate_operation_result(_seed_ngfw(request_matches=False))
        assert disposition == OperationResultDisposition.REJECTED_OWNERSHIP


class TestApplyPendingOperationResults:
    def test_records_disposition_and_returns_count(self):
        row = _seed()
        assert apply_pending_operation_results() == 1
        row.refresh_from_db()
        assert row.disposition == OperationResultDisposition.VALIDATED
        assert row.applied_at is not None

    def test_is_idempotent_and_skips_dispositioned_rows(self):
        _seed()
        assert apply_pending_operation_results() == 1
        assert apply_pending_operation_results() == 0  # already dispositioned

    def test_shadow_never_mutates_domain_state_audit_or_outbox(self):
        row = _seed()
        range_row = Range.objects.get(request__request_id=row.request_id)
        assert apply_pending_operation_results() == 1
        range_row.refresh_from_db()
        # Direct SQL stays authoritative: status unchanged, no notification emitted.
        assert range_row.status == Range.Status.PROVISIONING
        assert not RangeEventOutbox.objects.exists()

    def test_rejected_rows_are_dispositioned_not_applied(self):
        stale = _seed(current=False)
        assert apply_pending_operation_results() == 1
        stale.refresh_from_db()
        assert stale.disposition == OperationResultDisposition.REJECTED_STALE


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
class TestApplierConcurrency:
    def test_concurrent_appliers_do_not_double_process(self):
        """select_for_update(skip_locked=True) lets a second applier skip a row a
        first applier holds, so no result is evaluated twice."""
        import threading

        _seed()
        _seed()
        barrier = threading.Barrier(2)
        counts: list[int] = []

        def worker() -> None:
            barrier.wait()
            counts.append(apply_pending_operation_results(batch_size=1))
            connection.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Two rows, each claimed by exactly one worker: total evaluated == 2, and
        # every remaining row is dispositioned (none left PENDING).
        assert sum(counts) == 2
        assert not OperationResultInbox.objects.filter(disposition=OperationResultDisposition.PENDING).exists()


@pytest.mark.postgres
@pytest.mark.django_db
class TestOperationBoundaryEffectivePrivileges:
    """Prove the migration-0036 grants against real PostgreSQL (ADR-043-R1): the
    provisioner role may read the input and append to the inbox, and has no
    write access to either domain projection beyond that."""

    def _has(self, table: str, priv: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute("SELECT has_table_privilege('provisioner_lambda', %s, %s)", [table, priv])
            return bool(cursor.fetchone()[0])

    def test_provisioner_can_read_input_and_append_results_only(self):
        assert self._has("engine_operation_input", "SELECT") is True
        assert self._has("engine_operation_result_inbox", "INSERT") is True
        # No write access to the input; no update/delete on the inbox.
        assert self._has("engine_operation_input", "INSERT") is False
        assert self._has("engine_operation_input", "UPDATE") is False
        assert self._has("engine_operation_result_inbox", "UPDATE") is False
        assert self._has("engine_operation_result_inbox", "DELETE") is False
