"""Truthful, evidence-gated range cleanup-outcome projection (#2086, ADR-063-R4/R5).

verified_terminal is gated on durable scoped provider inventory/readback evidence,
never on a logical lifecycle status: a DESTROYED range with no evidence is
``pending`` with an unconfirmed-inventory obligation. A failed / dead-lettered /
absent range is ``unknown`` -- never an empty success.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import (
    CleanupVerificationOutcome,
    InterruptState,
    ProvisionerLaunchIntent,
    ProvisionerLaunchStatus,
    Range,
    Request,
)
from engine.services import (
    CLEANUP_NOT_APPLICABLE,
    CLEANUP_PENDING,
    CLEANUP_UNKNOWN,
    CLEANUP_VERIFIED_TERMINAL,
    project_range_cleanup_outcome,
    record_cleanup_verification,
)

pytestmark = pytest.mark.django_db
User = get_user_model()


def _range(status, *, operation_id=None):
    user = User.objects.create_user(username=f"{uuid4()}@example.com")
    request = Request.objects.create(request_id=uuid4(), request_type="range", user=user)
    Range.objects.create(
        workspace_id=1, request=request, user=user, status=status, provisioner_operation_id=operation_id
    )
    return request.request_id


def _verify(request_id, outcome, *, residuals=None):
    record_cleanup_verification(
        request_id=request_id,
        operation_id=uuid4(),
        outcome=outcome,
        scope={"categories": ["instances", "subnets"], "project": "proj-x"},
        residual_categories=residuals or [],
        observed_at=datetime.now(UTC),
    )


def test_active_range_owes_no_cleanup():
    outcome = project_range_cleanup_outcome(_range(Range.Status.PROVISIONING))
    assert outcome.cleanup == CLEANUP_NOT_APPLICABLE
    assert outcome.residual_obligations == []


def test_destroying_range_is_pending_with_obligation():
    outcome = project_range_cleanup_outcome(_range(Range.Status.DESTROYING))
    assert outcome.cleanup == CLEANUP_PENDING
    assert any(o.code == "teardown_in_progress" for o in outcome.residual_obligations)


def test_destroyed_without_evidence_is_pending_not_verified():
    outcome = project_range_cleanup_outcome(_range(Range.Status.DESTROYED))
    assert outcome.cleanup == CLEANUP_PENDING
    assert any(o.code == "provider_inventory_unconfirmed" for o in outcome.residual_obligations)


def test_destroyed_with_verified_evidence_is_verified_terminal():
    request_id = _range(Range.Status.DESTROYED)
    _verify(request_id, CleanupVerificationOutcome.VERIFIED_ABSENT.value)
    outcome = project_range_cleanup_outcome(request_id)
    assert outcome.cleanup == CLEANUP_VERIFIED_TERMINAL
    assert outcome.residual_obligations == []
    assert outcome.verification_observed_at is not None
    assert outcome.verification_scope is not None


def test_residuals_found_is_unknown_with_residual_obligations():
    request_id = _range(Range.Status.DESTROYED)
    _verify(
        request_id,
        CleanupVerificationOutcome.RESIDUALS_FOUND.value,
        residuals=[{"category": "instances", "count": 1}],
    )
    outcome = project_range_cleanup_outcome(request_id)
    assert outcome.cleanup == CLEANUP_UNKNOWN
    assert any(o.code == "residual_resource" for o in outcome.residual_obligations)


def test_incomplete_inventory_is_unknown():
    request_id = _range(Range.Status.DESTROYED)
    _verify(request_id, CleanupVerificationOutcome.INCOMPLETE.value)
    outcome = project_range_cleanup_outcome(request_id)
    assert outcome.cleanup == CLEANUP_UNKNOWN
    assert any(o.code == "inventory_incomplete" for o in outcome.residual_obligations)


def test_failed_range_is_unknown_not_empty_success():
    outcome = project_range_cleanup_outcome(_range(Range.Status.FAILED))
    assert outcome.cleanup == CLEANUP_UNKNOWN
    assert any(o.code == "operation_failed" for o in outcome.residual_obligations)


def test_absent_range_is_unknown_never_empty_success():
    outcome = project_range_cleanup_outcome(uuid4())
    assert outcome.found is False
    assert outcome.cleanup == CLEANUP_UNKNOWN
    assert any(o.code == "range_absent" for o in outcome.residual_obligations)


def test_dead_lettered_dispatch_adds_obligation():
    operation_id = uuid4()
    request_id = _range(Range.Status.DESTROYING, operation_id=operation_id)
    from django.utils import timezone

    ProvisionerLaunchIntent.objects.create(
        operation_id=operation_id,
        idempotency_key=str(uuid4()),
        payload={"version": 1, "resource": "raes-range", "operation": "destroy", "request_id": str(request_id)},
        status=ProvisionerLaunchStatus.DLQ,
        next_attempt_at=timezone.now(),
    )
    outcome = project_range_cleanup_outcome(request_id)
    assert outcome.cleanup == CLEANUP_PENDING
    assert any(o.code == "dispatch_dead_lettered" for o in outcome.residual_obligations)


def test_residuals_found_without_categories_still_flags_a_residual():
    # RESIDUALS_FOUND with no enumerated categories must still record a residual
    # obligation (absence is not proven), not silently drop to an empty success.
    request_id = _range(Range.Status.DESTROYED)
    _verify(request_id, CleanupVerificationOutcome.RESIDUALS_FOUND.value, residuals=[])
    outcome = project_range_cleanup_outcome(request_id)
    assert outcome.cleanup == CLEANUP_UNKNOWN
    assert any(
        o.code == "residual_resource" and "found residual resources" in o.detail for o in outcome.residual_obligations
    )


def test_interrupt_exhausted_adds_obligation():
    operation_id = uuid4()
    request_id = _range(Range.Status.DESTROYING, operation_id=operation_id)
    from django.utils import timezone

    ProvisionerLaunchIntent.objects.create(
        operation_id=operation_id,
        idempotency_key=str(uuid4()),
        payload={"version": 1, "resource": "raes-range", "operation": "provision", "request_id": str(request_id)},
        status=ProvisionerLaunchStatus.RUNNING,
        interrupt_state=InterruptState.EXHAUSTED,
        next_attempt_at=timezone.now(),
    )
    outcome = project_range_cleanup_outcome(request_id)
    assert any(o.code == "interrupt_exhausted" for o in outcome.residual_obligations)
