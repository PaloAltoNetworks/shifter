"""Warm-pool apply-path tests for ``engine.services._operation_apply_raes`` (#28).

The warm pool overloads the RAES terminal result apply with three warm-specific
transitions the SQLite coverage lane can prove:

- a warm-prepare terminal-READY realizes infrastructure but keeps the range
  quarantined (``Range.status`` unchanged) and flips the ledger row to READY;
- a warm activate terminal-READY settles the CLAIMED ledger row to ACTIVATED; and
- a terminal-FAILED moves a warm generation to UNHEALTHY so the reconciler
  actively destroys it (never leaves it waiting on a teardown that never runs).
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.models import OperationResultInbox, Range, Request, WarmRangeGeneration
from engine.services import apply_pending_operation_results
from engine.services._operation_apply_raes import (
    _pending_warm_generation,
    _retire_warm_generation_on_failure,
    _settle_warm_generation_on_activation,
)
from shared.operation_envelope import build_operation_envelope, canonical_payload_digest
from shared.operation_results import ResultStep, build_result_identity, result_kind_for
from shared.raes.status import RAES_STATE_SUCCEEDED

pytestmark = pytest.mark.django_db

_WORKSPACE_ID = 1


class _Fixture:
    """An RAES range owning a live operation generation plus a warm ledger row."""

    def __init__(self, *, operation="provision", status=Range.Status.PROVISIONING):
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

    def seed_generation(self, state):
        claimed = state == WarmRangeGeneration.State.CLAIMED
        now = timezone.now()
        return WarmRangeGeneration.objects.create(
            bucket_id="gce-polaris",
            compatibility_digest="sha256:" + "a" * 64,
            effective_policy_fingerprint="sha256:" + "f" * 64,
            backend="gce",
            range_source="mission-control",
            capacity_partition="default",
            capacity_scope_ref=uuid4(),
            capacity_draw_key=uuid4(),
            request_id=self.request_id,
            range=None,
            state=state,
            claimed_by_request_id=uuid4() if claimed else None,
            claimed_at=now if claimed else None,
        )

    def seed_result(self, step, payload):
        envelope = build_operation_envelope(
            operation_id=self.operation_id,
            request_id=self.request_id,
            resource="raes-range",
            operation=self.operation,
            payload=payload,
        )
        digest = canonical_payload_digest(envelope["payload"])
        return OperationResultInbox.objects.create(
            operation_id=self.operation_id,
            request_id=self.request_id,
            resource="raes-range",
            operation=self.operation,
            contract_version="1",
            result_kind=result_kind_for("raes-range", self.operation, step=step),
            result_step=step,
            result_identity=build_result_identity(operation_id=self.operation_id, step=step, digest=digest),
            payload_digest=digest,
            envelope=envelope,
        )


class TestWarmPrepareApply:
    def test_terminal_ready_keeps_quarantine_and_flips_ledger_ready(self):
        fx = _Fixture(status=Range.Status.PROVISIONING)
        gen = fx.seed_generation(WarmRangeGeneration.State.PROVISIONING)
        fx.seed_result(ResultStep.RAES_TERMINAL_READY, {"raes_status": RAES_STATE_SUCCEEDED, "members": []})

        apply_pending_operation_results()

        fx.range.refresh_from_db()
        gen.refresh_from_db()
        # Quarantine preserved: the range never becomes publicly READY on prepare.
        assert fx.range.status == Range.Status.PROVISIONING.value
        assert gen.state == WarmRangeGeneration.State.READY
        assert gen.range_id == fx.range.id
        assert gen.operation_id == fx.operation_id

    def test_terminal_failed_moves_generation_unhealthy(self):
        fx = _Fixture(status=Range.Status.PROVISIONING)
        gen = fx.seed_generation(WarmRangeGeneration.State.PROVISIONING)
        fx.seed_result(ResultStep.RAES_TERMINAL_FAILED, {"reason_code": "cloud_operation_failed", "diagnostic": ""})

        apply_pending_operation_results()

        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.UNHEALTHY


class TestSettleOnActivation:
    def test_activate_settles_claimed_to_activated(self):
        fx = _Fixture(operation="activate", status=Range.Status.PROVISIONING)
        gen = fx.seed_generation(WarmRangeGeneration.State.CLAIMED)
        row = SimpleNamespace(operation="activate", request_id=fx.request_id)
        _settle_warm_generation_on_activation(row, fx.range)
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.ACTIVATED

    def test_non_activate_operation_is_noop(self):
        fx = _Fixture(status=Range.Status.PROVISIONING)
        gen = fx.seed_generation(WarmRangeGeneration.State.CLAIMED)
        row = SimpleNamespace(operation="provision", request_id=fx.request_id)
        _settle_warm_generation_on_activation(row, fx.range)
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.CLAIMED

    def test_no_claimed_generation_is_noop(self):
        fx = _Fixture(operation="activate", status=Range.Status.PROVISIONING)
        row = SimpleNamespace(operation="activate", request_id=fx.request_id)
        # No CLAIMED generation exists: nothing to settle, and no error.
        _settle_warm_generation_on_activation(row, fx.range)


class TestPendingAndRetireHelpers:
    def test_pending_returns_provisioning_generation(self):
        fx = _Fixture()
        gen = fx.seed_generation(WarmRangeGeneration.State.PROVISIONING)
        row = SimpleNamespace(operation="provision", request_id=fx.request_id)
        assert _pending_warm_generation(row, fx.range).pk == gen.pk

    def test_pending_is_none_for_activate_operation(self):
        fx = _Fixture(operation="activate")
        fx.seed_generation(WarmRangeGeneration.State.PROVISIONING)
        row = SimpleNamespace(operation="activate", request_id=fx.request_id)
        assert _pending_warm_generation(row, fx.range) is None

    def test_retire_on_failure_moves_claimed_unhealthy(self):
        fx = _Fixture(operation="activate")
        gen = fx.seed_generation(WarmRangeGeneration.State.CLAIMED)
        row = SimpleNamespace(operation="activate", request_id=fx.request_id)
        _retire_warm_generation_on_failure(row, fx.range)
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.UNHEALTHY

    def test_retire_on_failure_no_generation_is_noop(self):
        fx = _Fixture()
        row = SimpleNamespace(operation="provision", request_id=fx.request_id)
        # No warm generation for the request: nothing to retire, and no error.
        _retire_warm_generation_on_failure(row, fx.range)

    def test_pending_is_none_when_range_has_no_request(self):
        row = SimpleNamespace(operation="provision", request_id=uuid4())
        range_obj = SimpleNamespace(request=None)
        assert _pending_warm_generation(row, range_obj) is None

    def test_retire_on_failure_none_when_range_has_no_request(self):
        row = SimpleNamespace(operation="provision", request_id=uuid4())
        range_obj = SimpleNamespace(request=None)
        # No request to correlate: the retire helper is a safe no-op.
        _retire_warm_generation_on_failure(row, range_obj)
