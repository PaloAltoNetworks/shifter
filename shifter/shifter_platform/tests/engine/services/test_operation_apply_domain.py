"""Tests for the authoritative operation-result apply (ADR-043 phase 4, #1836).

Phase 2 (#1834) left the applier in shadow for every resource. This suite covers
what phase 4 adds: the pause/resume + NGFW family is applied to domain state,
under lock, with a strict audit row and the ADR-025 notification, and refuses
anything it cannot prove it owns.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from engine.models import (
    App,
    Instance,
    OperationResultDisposition,
    OperationResultInbox,
    Range,
    RangeEventOutbox,
    Request,
)
from engine.services import apply_pending_operation_results
from shared.audit import bind_audit_writer, get_audit_writer, reset_audit_writer
from shared.enums import ResourceStatus
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
from shared.operation_results import ResultStep, build_result_identity, result_kind_for

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db


class _Fixture:
    """A range owning a live operation generation, optionally with an NGFW."""

    def __init__(
        self, *, operation: str = "pause", status: str = ResourceStatus.PAUSING.value, with_ngfw: bool = False
    ):
        self.operation = operation
        self.operation_id = uuid4()
        self.request_id = uuid4()
        self.user = get_user_model().objects.create_user(username=f"{self.request_id}@example.com")
        self.request = Request.objects.create(request_id=self.request_id, request_type="range", user=self.user)
        self.ngfw = None
        self.ngfw_app = None
        if with_ngfw:
            self.ngfw = Instance.objects.create(
                request=self.request,
                role=Instance.Role.NGFW,
                status=ResourceStatus.READY.value,
            )
            self.ngfw_app = App.objects.create(
                request=self.request,
                instance=self.ngfw,
                app_type=App.AppType.NGFW,
                status=ResourceStatus.READY.value,
            )
        self.range = Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=self.request,
            user=self.user,
            status=status,
            provisioner_operation_id=self.operation_id,
            ngfw_instance=self.ngfw,
        )

    def instance(self, status: str = ResourceStatus.READY.value) -> Instance:
        return Instance.objects.create(request=self.request, role=Instance.Role.VICTIM, status=status)

    def seed(
        self,
        step: ResultStep,
        payload: dict,
        *,
        resource: str = "range",
        operation_id=None,
        digest_override: str | None = None,
    ) -> OperationResultInbox:
        operation_id = operation_id or self.operation_id
        envelope = build_operation_envelope(
            operation_id=operation_id,
            request_id=self.request_id,
            resource=resource,
            operation=self.operation,
            payload=payload,
        )
        digest = digest_override or canonical_payload_digest(envelope["payload"])
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


class _FailingAuditWriter:
    """An audit writer whose persistence always fails."""

    def write(self, event) -> None:
        raise RuntimeError("audit writer down")


def _disposition(row: OperationResultInbox) -> str:
    row.refresh_from_db()
    return row.disposition


class TestInstanceStateIsApplied:
    def test_named_instances_reach_the_reported_status(self):
        fx = _Fixture()
        target = fx.instance()
        row = fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(target.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        target.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert target.status == ResourceStatus.PAUSED.value

    def test_instances_outside_the_operations_request_are_refused(self):
        # A blanket update-by-request is the anti-pattern this guards: the result
        # names a UUID that does not belong to this operation's request.
        fx = _Fixture()
        other = _Fixture()
        stranger = other.instance()
        row = fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(stranger.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        stranger.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.REJECTED_OWNERSHIP
        assert stranger.status == ResourceStatus.READY.value

    def test_unnamed_sibling_instances_are_left_alone(self):
        fx = _Fixture()
        named = fx.instance()
        untouched = fx.instance()
        fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(named.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        untouched.refresh_from_db()
        assert untouched.status == ResourceStatus.READY.value


class TestTerminalTransition:
    def test_range_terminal_writes_status_and_notification(self):
        fx = _Fixture()
        row = fx.seed(ResultStep.RANGE_TERMINAL_PAUSED, {"status": ResourceStatus.PAUSED.value})
        apply_pending_operation_results()
        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.PAUSED.value
        assert fx.range.paused_at is not None
        assert RangeEventOutbox.objects.filter(payload__range_id=fx.range.id).exists()

    def test_failure_carries_only_the_authored_reason_code(self):
        fx = _Fixture()
        row = fx.seed(
            ResultStep.RANGE_TERMINAL_FAILED,
            {"reason_code": "cloud_operation_failed", "diagnostic": "stop timed out on i-0abc"},
        )
        apply_pending_operation_results()
        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.FAILED.value
        # The bounded diagnostic is not promoted into user-visible range error text.
        assert fx.range.error_message == "cloud_operation_failed"
        assert "i-0abc" not in fx.range.error_message


class TestOrderingAndTerminality:
    def test_late_progress_after_terminal_does_not_regress_state(self):
        fx = _Fixture()
        target = fx.instance()
        fx.seed(ResultStep.RANGE_TERMINAL_PAUSED, {"status": ResourceStatus.PAUSED.value})
        apply_pending_operation_results()

        late = fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(target.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        fx.range.refresh_from_db()
        target.refresh_from_db()
        assert _disposition(late) == OperationResultDisposition.REJECTED_ORDERING
        assert fx.range.status == ResourceStatus.PAUSED.value
        assert target.status == ResourceStatus.READY.value

    def test_conflicting_replay_for_one_step_is_rejected(self):
        fx = _Fixture()
        one = fx.instance()
        two = fx.instance()
        fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(one.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(two.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        dispositions = set(OperationResultInbox.objects.values_list("disposition", flat=True))
        assert dispositions == {OperationResultDisposition.REJECTED_CONFLICT}
        one.refresh_from_db()
        two.refresh_from_db()
        assert one.status == ResourceStatus.READY.value
        assert two.status == ResourceStatus.READY.value


class TestNgfwCascadeOwnership:
    def test_cascade_applies_to_the_ranges_attached_ngfw(self):
        fx = _Fixture(with_ngfw=True)
        row = fx.seed(
            ResultStep.RANGE_NGFW_CASCADE_PAUSED,
            {"ngfw_instance_uuid": str(fx.ngfw.uuid), "status": ResourceStatus.PAUSED.value},
        )
        apply_pending_operation_results()
        fx.ngfw.refresh_from_db()
        fx.ngfw_app.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.ngfw.status == ResourceStatus.PAUSED.value
        assert fx.ngfw_app.status == ResourceStatus.PAUSED.value

    def test_cascade_to_an_unattached_ngfw_is_refused(self):
        # One range generation must not be able to mutate an arbitrary NGFW.
        fx = _Fixture(with_ngfw=True)
        other = _Fixture(with_ngfw=True)
        row = fx.seed(
            ResultStep.RANGE_NGFW_CASCADE_PAUSED,
            {"ngfw_instance_uuid": str(other.ngfw.uuid), "status": ResourceStatus.PAUSED.value},
        )
        apply_pending_operation_results()
        other.ngfw.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.REJECTED_OWNERSHIP
        assert other.ngfw.status == ResourceStatus.READY.value

    def test_cascade_pause_is_refused_while_another_range_needs_the_ngfw(self):
        fx = _Fixture(with_ngfw=True)
        Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=Request.objects.create(request_id=uuid4(), request_type="range", user=fx.user),
            user=fx.user,
            status=ResourceStatus.READY.value,
            ngfw_instance=fx.ngfw,
        )
        row = fx.seed(
            ResultStep.RANGE_NGFW_CASCADE_PAUSED,
            {"ngfw_instance_uuid": str(fx.ngfw.uuid), "status": ResourceStatus.PAUSED.value},
        )
        apply_pending_operation_results()
        fx.ngfw.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.REJECTED_OWNERSHIP
        assert fx.ngfw.status == ResourceStatus.READY.value

    def test_only_the_ngfw_app_projection_is_touched(self):
        fx = _Fixture(with_ngfw=True)
        other_app = App.objects.create(
            request=fx.request,
            instance=fx.ngfw,
            app_type=App.AppType.OS,
            status=ResourceStatus.READY.value,
        )
        fx.seed(
            ResultStep.RANGE_NGFW_CASCADE_PAUSED,
            {"ngfw_instance_uuid": str(fx.ngfw.uuid), "status": ResourceStatus.PAUSED.value},
        )
        apply_pending_operation_results()
        other_app.refresh_from_db()
        assert other_app.status == ResourceStatus.READY.value


class TestInstanceResultsCannotReachTheNgfw:
    def test_instance_result_naming_the_attached_ngfw_is_refused(self):
        # The provisioner principal's one capability is an inbox INSERT. An
        # otherwise-valid instance result naming the attached NGFW must not move
        # it: that would bypass the cascade's attachment and keep-alive checks.
        fx = _Fixture(with_ngfw=True)
        row = fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(fx.ngfw.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        fx.ngfw.refresh_from_db()
        fx.ngfw_app.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.REJECTED_OWNERSHIP
        assert fx.ngfw.status == ResourceStatus.READY.value
        assert fx.ngfw_app.status == ResourceStatus.READY.value

    def test_a_shared_ngfw_is_not_moved_by_another_ranges_instance_result(self):
        fx = _Fixture(with_ngfw=True)
        Range.objects.create(
            workspace_id=_WORKSPACE_ID,
            request=Request.objects.create(request_id=uuid4(), request_type="range", user=fx.user),
            user=fx.user,
            status=ResourceStatus.READY.value,
            ngfw_instance=fx.ngfw,
        )
        fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(fx.ngfw.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        fx.ngfw.refresh_from_db()
        assert fx.ngfw.status == ResourceStatus.READY.value


class TestSiblingResultsAreSerialized:
    def test_a_later_result_does_not_jump_ahead_of_a_pending_earlier_one(self):
        # skip_locked lets a worker reach a later row first. Applying it would
        # make the earlier step arrive "late" and be wrongly rejected, so the
        # later row waits instead.
        fx = _Fixture()
        target = fx.instance()
        earlier = fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(target.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        later = fx.seed(ResultStep.RANGE_TERMINAL_PAUSED, {"status": ResourceStatus.PAUSED.value})

        # Hide the earlier row from this pass, as skip_locked would.
        OperationResultInbox.objects.filter(pk=later.pk).update(created_at=earlier.created_at)
        assert _disposition(later) == OperationResultDisposition.PENDING

        apply_pending_operation_results()
        # Both eventually apply, and the range only reaches its terminal state
        # after the instance step it depends on.
        assert _disposition(earlier) == OperationResultDisposition.APPLIED
        target.refresh_from_db()
        assert target.status == ResourceStatus.PAUSED.value


class TestGenerationFence:
    def test_result_for_a_rotated_generation_is_stale(self):
        fx = _Fixture()
        row = fx.seed(
            ResultStep.RANGE_TERMINAL_PAUSED,
            {"status": ResourceStatus.PAUSED.value},
            operation_id=uuid4(),
        )
        apply_pending_operation_results()
        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.REJECTED_STALE
        assert fx.range.status == ResourceStatus.PAUSING.value


class TestAuditIsTheControl:
    def test_audit_failure_rolls_back_the_domain_write(self):
        # ADR-043-R3: the audit row is the control, not a convenience. If it
        # cannot be written the transition must not survive.
        fx = _Fixture()
        row = fx.seed(ResultStep.RANGE_TERMINAL_PAUSED, {"status": ResourceStatus.PAUSED.value})
        # Bind a failing writer through the audit port's designed seam rather
        # than patching the caller, so the failure travels the real code path.
        # Binding fails closed over an existing writer, so clear it first and
        # restore the startup binding afterwards.
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
        row.refresh_from_db()
        assert fx.range.status == ResourceStatus.PAUSING.value
        assert row.disposition == OperationResultDisposition.PENDING
        assert not RangeEventOutbox.objects.filter(payload__range_id=fx.range.id).exists()


@pytest.mark.postgres
@pytest.mark.django_db
class TestPhase4EffectivePrivileges:
    """Prove the phase-4 revokes against real PostgreSQL (ADR-043-R1).

    A migration emitting a REVOKE string is not evidence; effective privilege is.
    These assertions are deliberately two-sided: they prove what was revoked AND
    prove the grants a live writer outside this family still depends on survived,
    so an over-broad revoke fails here rather than in production.
    """

    def _table(self, table: str, priv: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute("SELECT has_table_privilege('provisioner_lambda', %s, %s)", [table, priv])
            return bool(cursor.fetchone()[0])

    def _column(self, table: str, column: str, priv: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT has_column_privilege('provisioner_lambda', %s, %s, %s)",
                [table, column, priv],
            )
            return bool(cursor.fetchone()[0])

    def test_ngfw_app_writes_are_revoked(self):
        # Every NGFW-family engine_app writer now reports results instead:
        # the cascade, the direct provision/deprovision/start/stop path, and the
        # attachment bookkeeping that used to re-write App status as a side effect.
        assert self._table("engine_app", "UPDATE") is False

    def test_ngfw_app_reads_survive(self):
        # Still read by ngfw_runtime / provisioner_db_ngfw / range_ops._ngfw.
        assert self._table("engine_app", "SELECT") is True

    def test_engine_instance_writes_survive_for_the_uncut_family(self):
        # Cyberscript range provision still writes engine_instance
        # (provisioner_db._write_instance_states). Revoking this would break
        # provisioning; it belongs to the residual teardown (#1839).
        assert self._table("engine_instance", "UPDATE") is True

    def test_range_gwlb_endpoint_write_is_revoked(self):
        assert self._column("mission_control_range", "gwlb_endpoint_id", "UPDATE") is False

    def test_range_ngfw_instance_write_survives(self):
        # Still written by provisioner_db.write_provisioned_state.
        assert self._column("mission_control_range", "ngfw_instance_id", "UPDATE") is True

    def test_inbox_append_still_works_and_reads_stay_denied(self):
        # The append boundary must keep working without ever gaining a read.
        assert self._table("engine_operation_result_inbox", "INSERT") is True
        assert self._table("engine_operation_result_inbox", "SELECT") is False
        assert self._table("engine_operation_result_inbox", "UPDATE") is False
        assert self._table("engine_operation_input", "SELECT") is True


@pytest.mark.postgres
@pytest.mark.django_db
class TestApplyRunsOnPostgres:
    """Exercise the locking path on the real backend.

    The rest of this suite runs on SQLite, which accepts locking constructs
    PostgreSQL rejects -- notably ``SELECT ... FOR UPDATE`` over the nullable
    side of an outer join, which is what a ``select_related("ngfw_instance")``
    on the locking query would produce. Without these, that class of defect
    reaches production unseen.
    """

    def test_instance_result_applies_under_real_row_locks(self):
        fx = _Fixture()
        target = fx.instance()
        row = fx.seed(
            ResultStep.RANGE_INSTANCES_PAUSED,
            {"instances": [{"instance_uuid": str(target.uuid), "status": ResourceStatus.PAUSED.value}]},
        )
        apply_pending_operation_results()
        target.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert target.status == ResourceStatus.PAUSED.value

    def test_cascade_applies_under_real_row_locks(self):
        # The cascade path locks the Range, then resolves and locks the nullable
        # NGFW FK separately. This is the exact shape PostgreSQL rejects if the
        # two are combined into one locking join.
        fx = _Fixture(with_ngfw=True)
        row = fx.seed(
            ResultStep.RANGE_NGFW_CASCADE_PAUSED,
            {"ngfw_instance_uuid": str(fx.ngfw.uuid), "status": ResourceStatus.PAUSED.value},
        )
        apply_pending_operation_results()
        fx.ngfw.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.ngfw.status == ResourceStatus.PAUSED.value

    def test_range_without_attached_ngfw_still_locks_cleanly(self):
        # Regression guard for the nullable-join case specifically: a Range whose
        # ngfw_instance is NULL must still be lockable.
        fx = _Fixture()
        row = fx.seed(ResultStep.RANGE_TERMINAL_PAUSED, {"status": ResourceStatus.PAUSED.value})
        apply_pending_operation_results()
        fx.range.refresh_from_db()
        assert _disposition(row) == OperationResultDisposition.APPLIED
        assert fx.range.status == ResourceStatus.PAUSED.value
