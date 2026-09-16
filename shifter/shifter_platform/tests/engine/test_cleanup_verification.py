"""Cleanup verification evidence record/read + prune command (#2086, ADR-063-R4/R5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from engine.models import CleanupVerificationOutcome, PublicOperationRetryBinding, RetryBindingStatus
from engine.services import (
    is_cleanup_verified_absent,
    latest_cleanup_verification,
    record_cleanup_verification,
)

pytestmark = pytest.mark.django_db


def _record(request_id, outcome, observed_at=None):
    record_cleanup_verification(
        request_id=request_id,
        operation_id=uuid4(),
        outcome=outcome,
        scope={"categories": ["instances", "subnets"]},
        residual_categories=[],
        observed_at=observed_at or datetime.now(UTC),
    )


def test_absent_when_no_evidence():
    assert latest_cleanup_verification(uuid4()) is None
    assert is_cleanup_verified_absent(uuid4()) is False


def test_verified_absent_reported():
    request_id = uuid4()
    _record(request_id, CleanupVerificationOutcome.VERIFIED_ABSENT.value)
    assert is_cleanup_verified_absent(request_id) is True
    view = latest_cleanup_verification(request_id)
    assert view is not None
    assert view.outcome == CleanupVerificationOutcome.VERIFIED_ABSENT.value


def test_latest_supersedes_earlier():
    request_id = uuid4()
    _record(request_id, CleanupVerificationOutcome.VERIFIED_ABSENT.value, observed_at=datetime.now(UTC))
    # A later re-inventory finds residuals -> supersedes -> no longer verified absent.
    _record(request_id, CleanupVerificationOutcome.RESIDUALS_FOUND.value, observed_at=datetime.now(UTC))
    assert is_cleanup_verified_absent(request_id) is False


def _binding(request_id, *, expired):
    delta = timedelta(hours=1)
    PublicOperationRetryBinding.objects.create(
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


def test_cleanup_verification_str_names_request_and_outcome():
    from engine.models import RangeCleanupVerification

    request_id = uuid4()
    row = RangeCleanupVerification(request_id=request_id, outcome=CleanupVerificationOutcome.VERIFIED_ABSENT.value)
    rendered = str(row)
    assert str(request_id) in rendered
    assert CleanupVerificationOutcome.VERIFIED_ABSENT.value in rendered


def test_prune_command_removes_only_verified_expired_bindings():
    verified = uuid4()
    _binding(verified, expired=True)
    _record(verified, CleanupVerificationOutcome.VERIFIED_ABSENT.value)
    _binding(uuid4(), expired=True)  # expired but no evidence -> retained

    out = StringIO()
    call_command("prune_retry_bindings", stdout=out)

    assert "Pruned 1" in out.getvalue()
    assert PublicOperationRetryBinding.objects.count() == 1
