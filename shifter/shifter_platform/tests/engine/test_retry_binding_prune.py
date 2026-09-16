"""Retention pruning gates on inventory evidence, never logical status (#2086, ADR-063-R4/R5).

A binding is prunable only when its retention window has elapsed AND the bound
operation's cleanup is verified absent by scoped provider inventory/readback
evidence. A logical DESTROYED status, a missing range, or a FAILED range is never
proof of absence, so those bindings (the recovery/residual evidence) are retained.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from engine.models import CleanupVerificationOutcome, PublicOperationRetryBinding, RetryBindingStatus
from engine.retry_binding import prune_expired_retry_bindings
from engine.services import record_cleanup_verification

pytestmark = pytest.mark.django_db


def _binding(request_id, *, expired: bool):
    delta = timedelta(hours=1)
    return PublicOperationRetryBinding.objects.create(
        deployment_scope="proj",
        actor_key="1",
        action="raes-range:provision",
        caller_key=str(uuid4()),
        request_id=request_id,
        operation_id=uuid4(),
        intent_digest="sha256:" + "a" * 64,
        intent_projection_version="1",
        status=RetryBindingStatus.ACTIVE,
        expires_at=timezone.now() - delta if expired else timezone.now() + delta,
    )


def _verify(request_id, outcome):
    record_cleanup_verification(
        request_id=request_id,
        operation_id=uuid4(),
        outcome=outcome,
        scope={"categories": ["instances"]},
        residual_categories=[],
        observed_at=datetime.now(UTC),
    )


def test_prunes_expired_binding_with_verified_absent_evidence():
    request_id = uuid4()
    _binding(request_id, expired=True)
    _verify(request_id, CleanupVerificationOutcome.VERIFIED_ABSENT.value)
    assert prune_expired_retry_bindings(batch_size=10) == 1
    assert PublicOperationRetryBinding.objects.count() == 0


def test_retains_expired_binding_without_evidence():
    _binding(uuid4(), expired=True)
    assert prune_expired_retry_bindings(batch_size=10) == 0
    assert PublicOperationRetryBinding.objects.count() == 1


def test_retains_expired_binding_with_residuals_found():
    request_id = uuid4()
    _binding(request_id, expired=True)
    _verify(request_id, CleanupVerificationOutcome.RESIDUALS_FOUND.value)
    assert prune_expired_retry_bindings(batch_size=10) == 0


def test_retains_unexpired_binding_even_when_verified():
    request_id = uuid4()
    _binding(request_id, expired=False)
    _verify(request_id, CleanupVerificationOutcome.VERIFIED_ABSENT.value)
    assert prune_expired_retry_bindings(batch_size=10) == 0
