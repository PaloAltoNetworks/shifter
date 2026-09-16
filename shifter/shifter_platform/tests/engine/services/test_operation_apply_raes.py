"""Authoritative apply for RAES operation results (ADR-043 phase 5, #1837).

Phase 4 made the applier authoritative for pause/resume + NGFW. This suite
covers what phase 5 adds: ``raes-range`` provision/destroy results drive the
Range lifecycle, persist the RAES sidecar evidence, write strict audit, and
enqueue the ADR-025 notification -- all in the applier's one transaction, with
snapshots deliberately excluded from audit and notification.

The pre-cutover path reached the same sidecar records through
``range.raes.operation`` / ``range.raes.snapshot`` outbox events. These tests
drive the result inbox instead, which is the authoritative seam.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.models import (
    InterruptState,
    OperationResultDisposition,
    OperationResultInbox,
    ProvisionerLaunchIntent,
    Range,
    RangeCleanupVerification,
    RangeEventOutbox,
    Request,
)
from engine.services import apply_pending_operation_results, is_cleanup_verified_absent
from shared.audit import bind_audit_writer, get_audit_writer, reset_audit_writer
from shared.enums import ResourceStatus
from shared.models import RaesOperationRecord
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
from shared.operation_results import ResultStep, build_result_identity, result_kind_for
from shared.raes.status import RAES_STATE_RUNNING, RAES_STATE_SUCCEEDED

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db


class _Fixture:
    """An RAES range owning a live operation generation."""

    def __init__(self, *, operation: str = "provision", status: str = ResourceStatus.PENDING.value):
        self.operation = operation
        self.operation_id = uuid4()
        self.request_id = uuid4()
        self.user = get_user_model().objects.create_user(username=f"{self.request_id}@example.com")
        self.request = Request.objects.create(request_id=self.request_id, request_type="range", user=self.user)
        self.range = Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=self.request,
            user=self.user,
            status=status,
            provisioner_operation_id=self.operation_id,
        )

    def seed(
        self,
        step: ResultStep,
        payload: dict,
        *,
        operation_id=None,
        resource: str = "raes-range",
    ) -> OperationResultInbox:
        operation_id = operation_id or self.operation_id
        envelope = build_operation_envelope(
            operation_id=operation_id,
            request_id=self.request_id,
            resource=resource,
            operation=self.operation,
            payload=payload,
        )
        digest = canonical_payload_digest(envelope["payload"])
        return OperationResultInbox.objects.create(
            operation_id=operation_id,
            request_id=self.request_id,
            resource=resource,
            operation=self.operation,
            contract_version="1",
            result_kind=result_kind_for(resource, self.operation, step=step),
            result_step=step,
            result_identity=build_result_identity(operation_id=operation_id, step=step, digest=digest),
            payload_digest=digest,
            envelope=envelope,
        )


@pytest.mark.parametrize("fault", [None, "missing", "os-mismatch", "stale-generation", "changed-plan"])
def test_v2_ready_requires_observed_completion_from_this_immutable_generation(fault):
    from pathlib import Path

    from engine.models import OperationInput
    from shared.raes.completion_evidence import build_completion_evidence
    from shared.raes.dispatch_port import ShifterDispatchResult
    from shared.raes.package_loader import launch_raes_package

    plans = []

    class Port:
        def realize(self, plan, participant_access=()):
            plans.append(plan)
            return ShifterDispatchResult("fixture", True, "accepted")

    scenario_path = Path(__file__).parents[2] / "shared/raes/fixtures/launchable/shifter-launch-min.sdl.yaml"
    assert launch_raes_package(scenario_path=scenario_path, port=Port()).accepted
    plan = plans[0]
    fx = _Fixture(status=Range.Status.PROVISIONING.value)
    fx.range.range_config = plan
    fx.range.save(update_fields=["range_config"])
    OperationInput.objects.create(
        operation_id=fx.operation_id,
        request_id=fx.request_id,
        resource="raes-range",
        operation="provision",
        contract_version="1",
        envelope=build_operation_envelope(
            operation_id=fx.operation_id,
            request_id=fx.request_id,
            resource="raes-range",
            operation="provision",
            payload={"plan": plan},
        ),
    )
    evidence = build_completion_evidence(
        plan,
        generation_id=str(fx.operation_id),
        resources=[
            {"address": address, "resource_type": resource["resource_type"], "status": "provisioned"}
            for address, resource in plan["resources"].items()
        ],
        operating_systems=[
            {
                "instance_key": "provision.node.web#0",
                "family": "linux",
                "distribution": "x-shifter:alpine",
                "version": "3.19",
            }
        ],
        compute_substrates=[{"instance_key": "provision.node.web#0", "value": "virtual-machine"}],
    )
    if fault == "os-mismatch":
        evidence["operating_systems"][0]["version"] = "3.20"
    elif fault == "stale-generation":
        evidence["generation_id"] = str(uuid4())
    elif fault == "changed-plan":
        evidence["plan_digest"] = "sha256:" + "0" * 64
    payload = {"raes_status": RAES_STATE_SUCCEEDED, "members": []}
    if fault != "missing":
        payload["completion"] = evidence
    row = fx.seed(ResultStep.RAES_TERMINAL_READY, payload)
    apply_pending_operation_results()
    fx.range.refresh_from_db()
    if fault is None:
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == Range.Status.READY
    else:
        assert _disposition(row) == OperationResultDisposition.REJECTED_INVALID
        assert fx.range.status == Range.Status.PROVISIONING


def _disposition(row: OperationResultInbox) -> str:
    row.refresh_from_db()
    return row.disposition


def _snapshot(count: int = 2) -> dict:
    return {
        "resources": [
            {"address": f"node.n{index}", "resource_type": "node", "status": "provisioned"} for index in range(count)
        ]
    }


def _cancel_generation(fx: _Fixture) -> ProvisionerLaunchIntent:
    """Record an active interrupt against the fixture's provision generation (#277)."""
    now = timezone.now()
    return ProvisionerLaunchIntent.objects.create(
        operation_id=fx.operation_id,
        idempotency_key=f"k-{fx.operation_id}",
        payload={"version": 1, "resource": "raes-range", "operation": "provision", "request_id": str(fx.request_id)},
        next_attempt_at=now,
        interrupt_state=InterruptState.REQUESTED,
        interrupt_requested_at=now,
        interrupt_next_attempt_at=now,
        interrupt_deadline=now + timedelta(seconds=1800),
    )


class TestCancelledGenerationFence:
    """A cancelled provision generation's results are evidence only (#277).

    The range must never be moved out of DESTROYING (no PROVISIONING/READY/FAILED,
    no provisioned state) by a generation whose provision was cancelled.
    """

    def test_terminal_ready_is_fenced_evidence_only(self):
        fx = _Fixture(status=Range.Status.DESTROYING.value)
        _cancel_generation(fx)
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, {"raes_status": RAES_STATE_SUCCEEDED, "members": []})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        # Applied as evidence, but the READY clobber is fenced.
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == Range.Status.DESTROYING.value
        assert fx.range.ready_at is None
        assert not fx.range.provisioned_instances
        assert RaesOperationRecord.objects.filter(request_id=fx.request_id, operation_id=str(fx.operation_id)).exists()

    def test_running_observation_is_fenced(self):
        fx = _Fixture(status=Range.Status.DESTROYING.value)
        _cancel_generation(fx)
        fx.seed(ResultStep.RAES_PROVISION_RUNNING, {"raes_status": RAES_STATE_RUNNING})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert fx.range.status == Range.Status.DESTROYING.value  # not PROVISIONING

    def test_terminal_failed_is_fenced(self):
        fx = _Fixture(status=Range.Status.DESTROYING.value)
        _cancel_generation(fx)
        fx.seed(ResultStep.RAES_TERMINAL_FAILED, {"reason_code": "cloud_operation_failed", "diagnostic": ""})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert fx.range.status == Range.Status.DESTROYING.value  # not FAILED

    def test_uncancelled_generation_still_reaches_ready(self):
        # Control: without an interrupt, the same READY result applies normally.
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        fx.seed(ResultStep.RAES_TERMINAL_READY, {"raes_status": RAES_STATE_SUCCEEDED, "members": []})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert fx.range.status == ResourceStatus.READY.value


class TestProvisionLifecycle:
    def test_running_moves_the_range_to_provisioning_and_records_evidence(self):
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_PROVISION_RUNNING, {"raes_status": RAES_STATE_RUNNING})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.PROVISIONING.value
        assert RaesOperationRecord.objects.filter(request_id=fx.request_id, operation_id=str(fx.operation_id)).exists()

    def test_terminal_success_moves_the_range_to_ready_and_notifies(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, {"raes_status": RAES_STATE_SUCCEEDED, "members": []})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.READY.value
        assert fx.range.ready_at is not None
        assert RangeEventOutbox.objects.count() == 1

    def test_evidence_carries_the_canonical_generation_not_the_request(self):
        # Historical sidecar rows used request_id as the operation id. New
        # results must carry the ADR-043 generation, or replay/fencing keys on
        # the wrong identity.
        fx = _Fixture()
        fx.seed(ResultStep.RAES_PROVISION_RUNNING, {"raes_status": RAES_STATE_RUNNING})

        apply_pending_operation_results()

        record = RaesOperationRecord.objects.get(request_id=fx.request_id)
        assert record.operation_id == str(fx.operation_id)
        assert record.operation_id != str(fx.request_id)


class TestSnapshotIsEvidenceOnly:
    def test_snapshot_persists_a_record_without_touching_lifecycle(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        row = fx.seed(ResultStep.RAES_PROVISION_SNAPSHOT, _snapshot())

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.PROVISIONING.value
        assert RaesOperationRecord.objects.filter(request_id=fx.request_id).count() == 1

    def test_snapshot_enqueues_no_range_event(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        fx.seed(ResultStep.RAES_PROVISION_SNAPSHOT, _snapshot())

        apply_pending_operation_results()

        assert RangeEventOutbox.objects.count() == 0


class TestDestroyLifecycle:
    def test_running_records_evidence_without_a_status_write(self):
        fx = _Fixture(operation="destroy", status=ResourceStatus.DESTROYING.value)
        row = fx.seed(ResultStep.RAES_DESTROY_RUNNING, {"raes_status": RAES_STATE_RUNNING})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.DESTROYING.value
        assert RangeEventOutbox.objects.count() == 0

    def test_terminal_destroyed_moves_the_range_and_notifies(self):
        fx = _Fixture(operation="destroy", status=ResourceStatus.DESTROYING.value)
        row = fx.seed(ResultStep.RAES_TERMINAL_DESTROYED, {"raes_status": RAES_STATE_SUCCEEDED})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.DESTROYED.value
        assert RangeEventOutbox.objects.count() == 1

    def test_terminal_destroyed_records_scoped_cleanup_inventory_evidence(self):
        # A terminal destroy carrying provider inventory/readback evidence records
        # a RangeCleanupVerification BEFORE the DESTROYED transition, so pruning and
        # verified_terminal gate on it, not the logical status (#2086, ADR-063-R4/R5).
        fx = _Fixture(operation="destroy", status=ResourceStatus.DESTROYING.value)
        row = fx.seed(
            ResultStep.RAES_TERMINAL_DESTROYED,
            {
                "raes_status": RAES_STATE_SUCCEEDED,
                "cleanup_inventory": {
                    "outcome": "VERIFIED_ABSENT",
                    "residual_categories": [],
                    "scope": {"project": "proj-x", "categories": ["instances"]},
                },
            },
        )

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.DESTROYED.value
        evidence = RangeCleanupVerification.objects.get(request_id=fx.request_id)
        assert evidence.outcome == "VERIFIED_ABSENT"
        assert str(evidence.operation_id) == str(fx.operation_id)
        assert evidence.scope == {"project": "proj-x", "categories": ["instances"]}
        assert is_cleanup_verified_absent(fx.request_id) is True


class TestFailure:
    def test_failure_records_only_the_authored_reason_code(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        row = fx.seed(
            ResultStep.RAES_TERMINAL_FAILED,
            {"reason_code": "cloud_operation_failed", "diagnostic": "gce insert returned 409 for node.web"},
        )

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.FAILED.value
        # The bounded diagnostic stays in the result payload; only the closed
        # reason code reaches user-visible range error text.
        assert fx.range.error_message == "cloud_operation_failed"
        assert "409" not in (fx.range.error_message or "")

    def test_failure_clears_the_generation(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        fx.seed(ResultStep.RAES_TERMINAL_FAILED, {"reason_code": "cloud_timeout", "diagnostic": ""})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert fx.range.provisioner_operation_id is None


class TestFencingAndOwnership:
    def test_a_stale_generation_is_refused(self):
        fx = _Fixture()
        row = fx.seed(ResultStep.RAES_PROVISION_RUNNING, {"raes_status": RAES_STATE_RUNNING})
        Range.objects.filter(pk=fx.range.pk).update(provisioner_operation_id=uuid4())

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.REJECTED_STALE
        assert fx.range.status == ResourceStatus.PENDING.value
        assert not RaesOperationRecord.objects.filter(request_id=fx.request_id).exists()

    def test_a_result_for_another_request_is_refused(self):
        fx = _Fixture()
        other = _Fixture()
        row = fx.seed(ResultStep.RAES_PROVISION_RUNNING, {"raes_status": RAES_STATE_RUNNING})
        OperationResultInbox.objects.filter(pk=row.pk).update(request_id=other.request_id)

        apply_pending_operation_results()

        assert _disposition(row) in {
            OperationResultDisposition.REJECTED_OWNERSHIP,
            OperationResultDisposition.REJECTED_INVALID,
        }
        assert not RaesOperationRecord.objects.filter(request_id=fx.request_id).exists()

    def test_late_progress_after_a_terminal_is_refused(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        fx.seed(ResultStep.RAES_TERMINAL_READY, {"raes_status": RAES_STATE_SUCCEEDED, "members": []})
        apply_pending_operation_results()

        late = fx.seed(ResultStep.RAES_PROVISION_RUNNING, {"raes_status": RAES_STATE_RUNNING})
        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert _disposition(late) == OperationResultDisposition.REJECTED_ORDERING
        assert fx.range.status == ResourceStatus.READY.value

    def test_a_conflicting_sibling_is_refused(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        fx.seed(ResultStep.RAES_PROVISION_SNAPSHOT, _snapshot(1))
        second = fx.seed(ResultStep.RAES_PROVISION_SNAPSHOT, _snapshot(2))

        apply_pending_operation_results()

        assert _disposition(second) == OperationResultDisposition.REJECTED_CONFLICT


class TestTransactionIntegrity:
    def test_an_audit_failure_rolls_back_the_whole_result(self):
        # ADR-043-R3: the audit row is the control, so best-effort auditing is
        # not sufficient. A failed audit must leave nothing half-applied.
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        row = fx.seed(ResultStep.RAES_TERMINAL_READY, {"raes_status": RAES_STATE_SUCCEEDED, "members": []})

        class _FailingAuditWriter:
            def write(self, event) -> None:
                raise RuntimeError("audit writer down")

        # Binding fails closed over an existing writer, so clear the startup
        # binding first and restore it afterwards.
        original = get_audit_writer()
        reset_audit_writer()
        bind_audit_writer(_FailingAuditWriter())
        try:
            with pytest.raises(RuntimeError, match="audit writer down"):
                apply_pending_operation_results()
        finally:
            reset_audit_writer()
            bind_audit_writer(original)

        fx.range.refresh_from_db()
        assert fx.range.status == ResourceStatus.PROVISIONING.value
        assert _disposition(row) == OperationResultDisposition.PENDING
        assert not RaesOperationRecord.objects.filter(request_id=fx.request_id).exists()

    def test_replaying_a_terminal_result_is_idempotent(self):
        fx = _Fixture(status=ResourceStatus.PROVISIONING.value)
        fx.seed(ResultStep.RAES_TERMINAL_READY, {"raes_status": RAES_STATE_SUCCEEDED, "members": []})
        apply_pending_operation_results()
        first_events = RangeEventOutbox.objects.count()

        # An identical replay collapses on result_identity at the append
        # boundary, so re-running the applier must not double-write.
        apply_pending_operation_results()

        fx.range.refresh_from_db()
        assert fx.range.status == ResourceStatus.READY.value
        assert RangeEventOutbox.objects.count() == first_events
        assert RaesOperationRecord.objects.filter(request_id=fx.request_id).count() == 1


@pytest.mark.postgres
@pytest.mark.django_db
class TestPhase5EffectivePrivileges:
    """Prove the phase-5 revokes against real PostgreSQL (ADR-043-R1).

    A migration emitting a REVOKE string is not evidence; effective privilege
    is. Two-sided on purpose: what the RAES cutover removed must be gone, and
    the grants the uncut cyberscript/NGFW families still depend on must survive,
    so an over-broad revoke fails here rather than in production.
    """

    def _table(self, table: str, priv: str) -> bool:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT has_table_privilege('provisioner_lambda', %s, %s)", [table, priv])
            return bool(cursor.fetchone()[0])

    def test_raes_delivery_binding_read_is_revoked(self):
        # Bindings now ride the operation input; the binding table read is gone.
        assert self._table("engine_raes_content_delivery_binding", "SELECT") is False

    def test_raes_image_registry_read_is_absent(self):
        # Never granted by migration 0027, and must not have arrived by any
        # other route (role inheritance, a schema-wide grant, default
        # privileges). Asserting effective privilege catches all of those; a
        # grep for a GRANT statement would not.
        assert self._table("engine_raes_image_mapping", "SELECT") is False

    def test_the_operation_boundary_still_works(self):
        assert self._table("engine_operation_input", "SELECT") is True
        assert self._table("engine_operation_result_inbox", "INSERT") is True
        assert self._table("engine_operation_result_inbox", "SELECT") is False

    def test_shared_reads_survive_for_the_uncut_families(self):
        # Cyberscript range provision/destroy (#1835 was closed NOT_PLANNED) and
        # the NGFW lookups still read these. Revoking them here would break a
        # live writer; they belong to the residual teardown (#1839).
        assert self._table("mission_control_range", "SELECT") is True
        assert self._table("engine_request", "SELECT") is True
        assert self._table("engine_instance", "SELECT") is True
