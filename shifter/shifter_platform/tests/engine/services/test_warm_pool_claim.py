"""PostgreSQL semantics proof for the warm-pool atomic claim (#28).

The claim is the pool's safety boundary: exactly one launch may own a ready
generation, an expired or mismatched generation is never claimed, and a launch
that claims twice is rejected by the partial-unique backstop. Only real
PostgreSQL proves ``select_for_update(skip_locked=True)`` one-winner semantics and
the partial-unique / check constraints; SQLite cannot (preflight #28).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.utils import timezone

from engine.models import Range, Request, WarmRangeGeneration
from engine.services import (
    admit_warm_generation_capacity,
    claim_ready_generation,
    warm_capacity_scope_ref,
)
from shared.capacity import CapacityOutcome

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]

_WORKSPACE_ID = 1
_DIGEST = "sha256:" + "a" * 64
_OTHER_DIGEST = "sha256:" + "b" * 64
_BUCKET = "gce-polaris"
_RANGE_SOURCE = "mission-control"
_CLAIM_BACKEND = "gce"


def _seed_ready_generation(*, bucket: str = _BUCKET, digest: str = _DIGEST, idle_delta: timedelta | None = None):
    """Create a system-owned Request/Range plus a READY warm generation."""
    request_id = uuid4()
    user = get_user_model().objects.create_user(username=f"warm-{request_id}@system.invalid")
    request = Request.objects.create(request_id=request_id, request_type="raes-range", user=user)
    range_row = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=Range.Status.READY,
    )
    now = timezone.now()
    gen = WarmRangeGeneration.objects.create(
        bucket_id=bucket,
        compatibility_digest=digest,
        effective_policy_fingerprint="sha256:" + "f" * 64,
        backend="gce",
        range_source="mission-control",
        capacity_partition="default",
        capacity_scope_ref=warm_capacity_scope_ref("shifter", bucket),
        capacity_draw_key=uuid4(),
        request_id=request.request_id,
        range=range_row,
        state=WarmRangeGeneration.State.READY,
        ready_at=now,
        idle_deadline=(now + idle_delta) if idle_delta is not None else None,
    )
    return gen


class TestClaimMatching:
    def test_claim_matches_ready_generation(self):
        gen = _seed_ready_generation()
        claimant = uuid4()
        claimed = claim_ready_generation(
            candidates=[(_BUCKET, _DIGEST)],
            backend=_CLAIM_BACKEND,
            range_source=_RANGE_SOURCE,
            claimant_request_id=claimant,
        )
        assert claimed is not None
        assert claimed.pk == gen.pk
        claimed.refresh_from_db()
        assert claimed.state == WarmRangeGeneration.State.CLAIMED
        assert claimed.claimed_by_request_id == claimant
        assert claimed.claimed_at is not None

    def test_claim_miss_on_digest_mismatch(self):
        _seed_ready_generation(digest=_DIGEST)
        assert (
            claim_ready_generation(
                candidates=[(_BUCKET, _OTHER_DIGEST)],
                backend=_CLAIM_BACKEND,
                range_source=_RANGE_SOURCE,
                claimant_request_id=uuid4(),
            )
            is None
        )

    def test_claim_miss_when_none_ready(self):
        assert (
            claim_ready_generation(
                candidates=[(_BUCKET, _DIGEST)],
                backend=_CLAIM_BACKEND,
                range_source=_RANGE_SOURCE,
                claimant_request_id=uuid4(),
            )
            is None
        )

    def test_claim_skips_expired_generation(self):
        _seed_ready_generation(idle_delta=timedelta(seconds=-1))
        assert (
            claim_ready_generation(
                candidates=[(_BUCKET, _DIGEST)],
                backend=_CLAIM_BACKEND,
                range_source=_RANGE_SOURCE,
                claimant_request_id=uuid4(),
            )
            is None
        )

    def test_claim_honors_unexpired_deadline(self):
        gen = _seed_ready_generation(idle_delta=timedelta(hours=1))
        claimed = claim_ready_generation(
            candidates=[(_BUCKET, _DIGEST)],
            backend=_CLAIM_BACKEND,
            range_source=_RANGE_SOURCE,
            claimant_request_id=uuid4(),
        )
        assert claimed is not None
        assert claimed.pk == gen.pk


class TestConcurrency:
    def test_concurrent_claims_single_winner(self):
        _seed_ready_generation()
        barrier = threading.Barrier(2)
        results: list[object] = []
        lock = threading.Lock()

        def _worker():
            barrier.wait()
            try:
                claimed = claim_ready_generation(
                    candidates=[(_BUCKET, _DIGEST)],
                    backend=_CLAIM_BACKEND,
                    range_source=_RANGE_SOURCE,
                    claimant_request_id=uuid4(),
                )
                with lock:
                    results.append(None if claimed is None else claimed.pk)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_worker) for _ in range(2)]
            for future in futures:
                future.result()

        winners = [r for r in results if r is not None]
        assert len(winners) == 1, f"exactly one claim must win, got {results}"
        # The single ready generation is now claimed, and a third claim misses.
        assert (
            claim_ready_generation(
                candidates=[(_BUCKET, _DIGEST)],
                backend=_CLAIM_BACKEND,
                range_source=_RANGE_SOURCE,
                claimant_request_id=uuid4(),
            )
            is None
        )


class TestPartialUniqueBackstop:
    def test_one_claim_per_request_rejected(self):
        gen_a = _seed_ready_generation()
        gen_b = _seed_ready_generation()
        claimant = uuid4()
        now = timezone.now()
        gen_a.state = WarmRangeGeneration.State.CLAIMED
        gen_a.claimed_by_request_id = claimant
        gen_a.claimed_at = now
        gen_a.save(update_fields=["state", "claimed_by_request_id", "claimed_at"])
        gen_b.state = WarmRangeGeneration.State.CLAIMED
        gen_b.claimed_by_request_id = claimant
        gen_b.claimed_at = now
        with pytest.raises(IntegrityError):
            gen_b.save(update_fields=["state", "claimed_by_request_id", "claimed_at"])


class TestPoolCapacity:
    def test_scope_ref_deterministic_and_bucket_scoped(self):
        a = warm_capacity_scope_ref("shifter", "gce-polaris")
        b = warm_capacity_scope_ref("shifter", "gce-polaris")
        c = warm_capacity_scope_ref("shifter", "gce-other")
        assert a == b
        assert a != c

    def test_admit_no_budget_is_indeterminate_and_nonblocking(self):
        scope = warm_capacity_scope_ref("shifter", _BUCKET)
        result = admit_warm_generation_capacity(scope_ref=scope, draw_key=uuid4())
        # No declared budget for this scope: the ledger has no opinion and does
        # not block, exactly as for an un-assessed range.
        assert result.outcome is CapacityOutcome.INDETERMINATE
        assert result.blocking is False
