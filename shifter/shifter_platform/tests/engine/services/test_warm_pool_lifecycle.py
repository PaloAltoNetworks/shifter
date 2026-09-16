"""SQLite-lane lifecycle tests for ``engine.services._warm_pool`` (#28).

The atomic-claim concurrency and DB-constraint proofs live in the PostgreSQL lane
(``test_warm_pool_claim``). This suite exercises the ledger lifecycle the SQLite
coverage lane can prove: create/query/count, single-threaded claim matching,
retire and recover transitions, finalize + capacity release, and the per-state
gauge counts. Provider dispatch (destroy / activation enqueue) is patched at the
seam so no launch intent is emitted.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.models import Range, Request, WarmRangeGeneration
from engine.services import (
    WarmGenerationDraft,
    active_generation_count,
    admit_warm_generation_capacity,
    bucket_state_counts,
    claim_ready_generation,
    create_warm_generation,
    enqueue_range_activation,
    finalize_retiring_generations,
    ready_generations,
    recover_stalled_generations,
    release_warm_generation_capacity,
    retire_generation,
    retire_generations_for_request,
    retire_removed_bucket_generations,
    total_active_generation_count,
    warm_capacity_scope_ref,
)
from shared.capacity import CapacityOutcome

pytestmark = pytest.mark.django_db

_BUCKET = "gce-polaris"
_DIGEST = "sha256:" + "a" * 64
_RANGE_SOURCE = "mission-control"
_BACKEND = "gce"


@pytest.fixture(autouse=True)
def _no_provider_dispatch(monkeypatch):
    """Patch the provider-facing seams so lifecycle tests emit no real dispatch."""
    monkeypatch.setattr(
        "engine.services._range_by_request.destroy_range_by_request", lambda request_id: True, raising=True
    )


def _seed_generation(
    *,
    state=WarmRangeGeneration.State.READY,
    bucket=_BUCKET,
    digest=_DIGEST,
    idle_delta: timedelta | None = None,
    with_range=True,
    range_status=Range.Status.READY,
    created_delta: timedelta | None = None,
):
    """Create a system-owned Request (+optional Range) and a warm generation row."""
    request_id = uuid4()
    user = get_user_model().objects.create_user(username=f"warm-{request_id}@system.invalid")
    request = Request.objects.create(request_id=request_id, request_type="raes-range", user=user)
    range_row = None
    if with_range:
        range_row = Range.objects.create(workspace_id=1, request=request, user=user, status=range_status)
    now = timezone.now()
    # The warmgen_claim_consistency check requires a CLAIMED row to record who
    # claimed it and when; an unclaimed non-retiring/terminal row must not.
    claimed = state == WarmRangeGeneration.State.CLAIMED
    gen = WarmRangeGeneration.objects.create(
        bucket_id=bucket,
        compatibility_digest=digest,
        effective_policy_fingerprint="sha256:" + "f" * 64,
        backend=_BACKEND,
        range_source=_RANGE_SOURCE,
        capacity_partition="default",
        capacity_scope_ref=uuid4(),
        capacity_draw_key=uuid4(),
        request_id=request.request_id,
        range=range_row,
        state=state,
        ready_at=now if state == WarmRangeGeneration.State.READY else None,
        claimed_by_request_id=uuid4() if claimed else None,
        claimed_at=now if claimed else None,
        idle_deadline=(now + idle_delta) if idle_delta is not None else None,
    )
    if created_delta is not None:
        WarmRangeGeneration.objects.filter(pk=gen.pk).update(created_at=now + created_delta)
        gen.refresh_from_db()
    return gen


class TestCreateAndQuery:
    def test_create_warm_generation_starts_provisioning(self):
        draft = WarmGenerationDraft(
            bucket_id=_BUCKET,
            compatibility_digest=_DIGEST,
            effective_policy_fingerprint="sha256:" + "f" * 64,
            backend=_BACKEND,
            range_source=_RANGE_SOURCE,
            capacity_partition="default",
            capacity_scope_ref=uuid4(),
            capacity_draw_key=uuid4(),
            request_id=uuid4(),
            idle_deadline=timezone.now() + timedelta(hours=1),
        )
        gen = create_warm_generation(draft)
        assert gen.state == WarmRangeGeneration.State.PROVISIONING
        assert gen.bucket_id == _BUCKET

    def test_ready_generations_oldest_first(self):
        first = _seed_generation(created_delta=timedelta(minutes=-10))
        second = _seed_generation(created_delta=timedelta(minutes=-1))
        result = ready_generations(_BUCKET)
        assert [g.pk for g in result] == [first.pk, second.pk]

    def test_active_counts_provisioning_and_ready_only(self):
        _seed_generation(state=WarmRangeGeneration.State.READY)
        _seed_generation(state=WarmRangeGeneration.State.PROVISIONING)
        _seed_generation(state=WarmRangeGeneration.State.CLAIMED)
        _seed_generation(state=WarmRangeGeneration.State.TERMINAL)
        assert active_generation_count(_BUCKET) == 2
        assert total_active_generation_count() == 2

    def test_bucket_state_counts_are_per_state(self):
        _seed_generation(state=WarmRangeGeneration.State.READY)
        _seed_generation(state=WarmRangeGeneration.State.READY)
        _seed_generation(state=WarmRangeGeneration.State.PROVISIONING)
        _seed_generation(state=WarmRangeGeneration.State.UNHEALTHY)
        counts = bucket_state_counts(_BUCKET)
        assert counts["ready"] == 2
        assert counts["provisioning"] == 1
        assert counts["unhealthy"] == 1
        assert counts["terminal"] == 0


class TestClaimMatching:
    def test_claim_matches_ready_generation(self):
        gen = _seed_generation()
        claimant = uuid4()
        claimed = claim_ready_generation(
            candidates=[(_BUCKET, _DIGEST)],
            backend=_BACKEND,
            range_source=_RANGE_SOURCE,
            claimant_request_id=claimant,
        )
        assert claimed is not None
        assert claimed.pk == gen.pk
        claimed.refresh_from_db()
        assert claimed.state == WarmRangeGeneration.State.CLAIMED
        assert claimed.claimed_by_request_id == claimant

    def test_claim_empty_candidates_is_none(self):
        _seed_generation()
        assert (
            claim_ready_generation(
                candidates=[], backend=_BACKEND, range_source=_RANGE_SOURCE, claimant_request_id=uuid4()
            )
            is None
        )

    def test_claim_miss_on_digest_mismatch(self):
        _seed_generation(digest=_DIGEST)
        assert (
            claim_ready_generation(
                candidates=[(_BUCKET, "sha256:" + "b" * 64)],
                backend=_BACKEND,
                range_source=_RANGE_SOURCE,
                claimant_request_id=uuid4(),
            )
            is None
        )

    def test_claim_skips_expired(self):
        _seed_generation(idle_delta=timedelta(seconds=-1))
        assert (
            claim_ready_generation(
                candidates=[(_BUCKET, _DIGEST)],
                backend=_BACKEND,
                range_source=_RANGE_SOURCE,
                claimant_request_id=uuid4(),
            )
            is None
        )

    def test_claim_honors_unexpired_deadline(self):
        gen = _seed_generation(idle_delta=timedelta(hours=1))
        claimed = claim_ready_generation(
            candidates=[(_BUCKET, _DIGEST)],
            backend=_BACKEND,
            range_source=_RANGE_SOURCE,
            claimant_request_id=uuid4(),
        )
        assert claimed is not None
        assert claimed.pk == gen.pk


class TestRetire:
    def test_retire_ready_moves_to_retiring(self):
        gen = _seed_generation()
        assert retire_generation(gen) is True
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.RETIRING

    def test_retire_skips_terminal_and_retiring(self):
        terminal = _seed_generation(state=WarmRangeGeneration.State.TERMINAL)
        retiring = _seed_generation(state=WarmRangeGeneration.State.RETIRING)
        assert retire_generation(terminal) is False
        assert retire_generation(retiring) is False

    def test_retire_swallows_dispatch_failure(self, monkeypatch):
        def _boom(request_id):
            raise RuntimeError("dispatch down")

        monkeypatch.setattr("engine.services._range_by_request.destroy_range_by_request", _boom, raising=True)
        gen = _seed_generation()
        # Dispatch failure is not fatal: the row stays RETIRING for a later retry.
        assert retire_generation(gen) is True
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.RETIRING

    def test_retire_removed_bucket_generations(self):
        _seed_generation(bucket="gce-polaris")
        _seed_generation(bucket="gce-gone")
        retired = retire_removed_bucket_generations(["gce-polaris"])
        assert retired == 1

    def test_retire_generations_for_request(self):
        gen = _seed_generation(state=WarmRangeGeneration.State.PROVISIONING)
        retired = retire_generations_for_request(gen.request_id)
        assert retired == 1
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.RETIRING


class TestRecoverStalled:
    def test_unhealthy_always_recovered(self):
        _seed_generation(state=WarmRangeGeneration.State.UNHEALTHY)
        assert recover_stalled_generations(_BUCKET, stall_grace_seconds=600) == 1

    def test_failed_range_recovered(self):
        _seed_generation(state=WarmRangeGeneration.State.PROVISIONING, range_status=Range.Status.FAILED)
        assert recover_stalled_generations(_BUCKET, stall_grace_seconds=600) == 1

    def test_never_realized_stalled_recovered(self):
        _seed_generation(
            state=WarmRangeGeneration.State.PROVISIONING,
            with_range=False,
            created_delta=timedelta(hours=-2),
        )
        assert recover_stalled_generations(_BUCKET, stall_grace_seconds=600) == 1

    def test_fresh_provisioning_not_recovered(self):
        _seed_generation(state=WarmRangeGeneration.State.PROVISIONING, with_range=False)
        assert recover_stalled_generations(_BUCKET, stall_grace_seconds=600) == 0

    def test_claimed_activation_stalled_recovered(self):
        _seed_generation(
            state=WarmRangeGeneration.State.CLAIMED,
            range_status=Range.Status.PROVISIONING,
            created_delta=timedelta(hours=-2),
        )
        assert recover_stalled_generations(_BUCKET, stall_grace_seconds=600) == 1


class TestFinalize:
    def test_retiring_with_destroyed_range_finalizes(self):
        gen = _seed_generation(state=WarmRangeGeneration.State.RETIRING, range_status=Range.Status.DESTROYED)
        assert finalize_retiring_generations(_BUCKET) == 1
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.TERMINAL
        assert gen.retired_at is not None

    def test_retiring_without_range_finalizes(self):
        gen = _seed_generation(state=WarmRangeGeneration.State.RETIRING, with_range=False)
        assert finalize_retiring_generations(_BUCKET) == 1
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.TERMINAL

    def test_activated_with_live_range_not_finalized(self):
        gen = _seed_generation(state=WarmRangeGeneration.State.ACTIVATED, range_status=Range.Status.READY)
        assert finalize_retiring_generations(_BUCKET) == 0
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.ACTIVATED

    def test_activated_with_destroyed_range_finalizes(self):
        gen = _seed_generation(state=WarmRangeGeneration.State.ACTIVATED, range_status=Range.Status.DESTROYED)
        assert finalize_retiring_generations(_BUCKET) == 1
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.TERMINAL

    def test_retiring_live_range_redispatches_destroy(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            "engine.services._range_by_request.destroy_range_by_request",
            lambda request_id: calls.append(request_id) or True,
            raising=True,
        )
        gen = _seed_generation(state=WarmRangeGeneration.State.RETIRING, range_status=Range.Status.PROVISIONING)
        assert finalize_retiring_generations(_BUCKET) == 0
        assert calls == [gen.request_id]

    def test_retiring_live_range_swallows_redispatch_failure(self, monkeypatch):
        def _boom(request_id):
            raise RuntimeError("destroy retry down")

        monkeypatch.setattr("engine.services._range_by_request.destroy_range_by_request", _boom, raising=True)
        gen = _seed_generation(state=WarmRangeGeneration.State.RETIRING, range_status=Range.Status.PROVISIONING)
        # A failed re-dispatch is swallowed: the row stays RETIRING for a later pass.
        assert finalize_retiring_generations(_BUCKET) == 0
        gen.refresh_from_db()
        assert gen.state == WarmRangeGeneration.State.RETIRING


class TestCapacity:
    def test_admit_no_budget_is_indeterminate_nonblocking(self):
        scope = warm_capacity_scope_ref("shifter", _BUCKET)
        result = admit_warm_generation_capacity(scope_ref=scope, draw_key=uuid4())
        assert result.outcome is CapacityOutcome.INDETERMINATE
        assert result.blocking is False

    def test_scope_ref_deterministic_and_bucket_scoped(self):
        first = warm_capacity_scope_ref("shifter", "b1")
        assert first == warm_capacity_scope_ref("shifter", "b1")
        assert first != warm_capacity_scope_ref("shifter", "b2")


class TestEnqueue:
    def test_enqueue_range_activation_dispatches(self, monkeypatch):
        seen: list = []
        monkeypatch.setattr(
            "engine.launch_intents.enqueue_provisioner_launch",
            lambda command: seen.append(command) or "intent-123",
            raising=True,
        )
        rid = uuid4()
        assert enqueue_range_activation(rid) == "intent-123"
        assert seen == [["raes-range", "activate", "--request-id", str(rid)]]

    def test_release_capacity_no_draw_is_idempotent(self):
        # No capacity draw exists for a random key: releasing is a harmless no-op.
        assert release_warm_generation_capacity(uuid4()) == 0
