"""Warm-pool reconciler tests (#28).

Two properties matter most and are pinned first: the digest the reconciler stamps
on a prepared generation must equal the digest the launch claim path computes for
the warm target class (or a prepared generation is never claimable), and a disabled
policy is a no-op. The rest exercises the reconcile pass: per-bucket retire of
stale/excess generations, bounded replenishment, gauge emission, the managed-user
lifecycle, and the fail-closed preparation cleanup -- with the provider dispatch,
admission, and reservation seams patched so no cloud work or launch intent is emitted.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from cms.services import _warm_pool_reconcile as wpr
from cms.services._warm_pool_claim import ISOLATION_PERSONAL
from cms.services._warm_pool_reconcile import (
    WARM_PURPOSE,
    WARM_RANGE_SOURCE,
    _bucket_compatibility_digest,
    reconcile_warm_pool,
)
from shared.warm_pool.compatibility import CompatibilityKey, compatibility_digest
from shared.warm_pool.policy import load_policy_json

_ENABLED = load_policy_json(
    '{"enabled": true, "replenish_concurrency": 4, "max_total_ready": 10,'
    ' "buckets": [{"id": "gce-polaris", "backend": "gce", "scenario": "polaris",'
    ' "capacity_partition": "default", "target": 2, "minimum": 0, "maximum": 5, "idle_ttl_seconds": 3600,'
    ' "region": "us-central1", "access_mode": "vpn"}]}'
)
_DISABLED = load_policy_json("")


class TestDigestParity:
    def test_reconciler_digest_matches_launch_claim_digest(self):
        """A generation the reconciler prepares is claimable by the warm target launch."""
        bucket = _ENABLED.buckets[0]
        package_digest = "sha256:" + "1" * 64
        lock_digest = "sha256:" + "2" * 64

        reconciler_digest = _bucket_compatibility_digest(bucket, package_digest=package_digest, lock_digest=lock_digest)
        launch_digest = compatibility_digest(
            CompatibilityKey(
                backend="gce",
                instantiation_purpose=WARM_PURPOSE.value,
                range_source=WARM_RANGE_SOURCE.value,
                workspace_isolation_class=ISOLATION_PERSONAL,
                egress_mode="status-quo",
                scenario=bucket.scenario,
                package_digest=package_digest,
                lock_digest=lock_digest,
            )
        )
        assert reconciler_digest == launch_digest

    def test_reconciler_digest_changes_with_package(self):
        bucket = _ENABLED.buckets[0]
        a = _bucket_compatibility_digest(bucket, package_digest="sha256:a", lock_digest="sha256:x")
        b = _bucket_compatibility_digest(bucket, package_digest="sha256:b", lock_digest="sha256:x")
        assert a != b


class TestReconcilePass:
    def test_disabled_policy_is_noop(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "WARM_POOL_POLICY", _DISABLED, raising=False)
        assert reconcile_warm_pool() == {"provisioned": 0, "retired": 0, "finalized": 0, "buckets": 0}

    def test_enabled_pass_reconciles_each_bucket_and_sweeps(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "WARM_POOL_POLICY", _ENABLED, raising=False)
        reconciled: list = []
        monkeypatch.setattr(
            wpr, "_reconcile_bucket", lambda bucket, policy, moment, summary: reconciled.append(bucket.id)
        )
        monkeypatch.setattr("engine.services.retire_removed_bucket_generations", lambda ids: 3)
        monkeypatch.setattr(wpr, "_emit_pool_gauges", lambda policy: None)

        summary = reconcile_warm_pool()
        assert reconciled == ["gce-polaris"]
        assert summary["buckets"] == 1
        assert summary["retired"] == 3

    def test_bucket_failure_is_isolated(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "WARM_POOL_POLICY", _ENABLED, raising=False)

        def _boom(bucket, policy, moment, summary):
            raise RuntimeError("bucket blew up")

        monkeypatch.setattr(wpr, "_reconcile_bucket", _boom)
        monkeypatch.setattr("engine.services.retire_removed_bucket_generations", lambda ids: 0)
        monkeypatch.setattr(wpr, "_emit_pool_gauges", lambda policy: None)
        # A single bucket's exception must not abort the pass.
        summary = reconcile_warm_pool()
        assert summary["buckets"] == 1


class TestReconcileBucketHelpers:
    def _bucket(self):
        return _ENABLED.buckets[0]

    def test_retire_stale_ready_partitions(self, monkeypatch):
        moment = __import__("django.utils.timezone", fromlist=["now"]).now()
        expired = SimpleNamespace(idle_deadline=moment, compatibility_digest="d")
        incompatible = SimpleNamespace(idle_deadline=None, compatibility_digest="other")
        live = SimpleNamespace(idle_deadline=None, compatibility_digest="d")
        monkeypatch.setattr("engine.services.ready_generations", lambda bucket_id: [expired, incompatible, live])
        monkeypatch.setattr("engine.services.retire_generation", lambda gen: True)
        survivors, retired = wpr._retire_stale_ready(self._bucket(), "d", moment)
        assert survivors == [live]
        assert retired == 2

    def test_scale_down_excess_oldest_first(self, monkeypatch):
        retired_gens: list = []
        monkeypatch.setattr("engine.services.retire_generation", lambda gen: retired_gens.append(gen) or True)
        bucket = SimpleNamespace(target=1)
        policy = SimpleNamespace(scale_down="oldest-first")
        live = [SimpleNamespace(name="a"), SimpleNamespace(name="b"), SimpleNamespace(name="c")]
        active, retired = wpr._scale_down_excess(bucket, policy, live, active=3)
        assert retired == 2
        assert active == 1
        assert [g.name for g in retired_gens] == ["a", "b"]

    def test_scale_down_excess_newest_first(self, monkeypatch):
        retired_gens: list = []
        monkeypatch.setattr("engine.services.retire_generation", lambda gen: retired_gens.append(gen) or True)
        bucket = SimpleNamespace(target=1)
        policy = SimpleNamespace(scale_down="newest-first")
        live = [SimpleNamespace(name="a"), SimpleNamespace(name="b"), SimpleNamespace(name="c")]
        _active, retired = wpr._scale_down_excess(bucket, policy, live, active=3)
        assert retired == 2
        assert [g.name for g in retired_gens] == ["c", "b"]

    def test_scale_down_no_excess_is_noop(self, monkeypatch):
        monkeypatch.setattr("engine.services.retire_generation", lambda gen: True)
        bucket = SimpleNamespace(target=3)
        policy = SimpleNamespace(scale_down="oldest-first")
        active, retired = wpr._scale_down_excess(bucket, policy, [], active=2)
        assert (active, retired) == (2, 0)

    def test_replenish_shortfall_bounded_by_budget(self, monkeypatch):
        monkeypatch.setattr("engine.services.total_active_generation_count", lambda: 0)
        provisioned_calls: list = []
        monkeypatch.setattr(
            wpr, "_provision_warm_generation", lambda bucket, policy, digest: provisioned_calls.append(digest) or True
        )
        # target=2, active=0 -> shortfall 2; maximum 5, ceiling 10, concurrency 4 -> budget 2.
        count = wpr._replenish_shortfall(self._bucket(), _ENABLED, "digest", active=0)
        assert count == 2
        assert len(provisioned_calls) == 2

    def test_replenish_none_when_at_target(self, monkeypatch):
        monkeypatch.setattr("engine.services.total_active_generation_count", lambda: 0)
        monkeypatch.setattr(wpr, "_provision_warm_generation", lambda *a: True)
        assert wpr._replenish_shortfall(self._bucket(), _ENABLED, "digest", active=2) == 0

    def test_replenish_capped_by_ceiling_headroom(self, monkeypatch):
        monkeypatch.setattr("engine.services.total_active_generation_count", lambda: 10)
        monkeypatch.setattr(wpr, "_provision_warm_generation", lambda *a: True)
        # ceiling 10 already fully drawn -> no headroom -> nothing provisioned.
        assert wpr._replenish_shortfall(self._bucket(), _ENABLED, "digest", active=0) == 0


class TestReconcileBucket:
    def test_unresolved_identity_retires_all_ready(self, monkeypatch):
        from django.utils import timezone

        monkeypatch.setattr("engine.services.finalize_retiring_generations", lambda b: 0)
        monkeypatch.setattr("engine.services.recover_stalled_generations", lambda b, **k: 0)
        monkeypatch.setattr(wpr, "_resolve_bucket_identity", lambda bucket: None)
        monkeypatch.setattr("engine.services.ready_generations", lambda b: [object(), object()])
        monkeypatch.setattr("engine.services.retire_generation", lambda gen: True)
        summary = {"provisioned": 0, "retired": 0, "finalized": 0, "buckets": 0}
        wpr._reconcile_bucket(_ENABLED.buckets[0], _ENABLED, timezone.now(), summary)
        assert summary["retired"] == 2
        assert summary["provisioned"] == 0

    def test_resolved_identity_retires_stale_and_replenishes(self, monkeypatch):
        from django.utils import timezone

        monkeypatch.setattr("engine.services.finalize_retiring_generations", lambda b: 1)
        monkeypatch.setattr("engine.services.recover_stalled_generations", lambda b, **k: 1)
        monkeypatch.setattr(wpr, "_resolve_bucket_identity", lambda bucket: ("sha256:p", "sha256:l"))
        monkeypatch.setattr(wpr, "_bucket_compatibility_digest", lambda bucket, **k: "current")
        monkeypatch.setattr(wpr, "_retire_stale_ready", lambda bucket, digest, moment: ([], 1))
        monkeypatch.setattr("engine.services.active_generation_count", lambda b: 0)
        monkeypatch.setattr(wpr, "_scale_down_excess", lambda bucket, policy, live, active: (active, 0))
        monkeypatch.setattr(wpr, "_replenish_shortfall", lambda bucket, policy, digest, active: 2)
        summary = {"provisioned": 0, "retired": 0, "finalized": 0, "buckets": 0}
        wpr._reconcile_bucket(_ENABLED.buckets[0], _ENABLED, timezone.now(), summary)
        assert summary == {"provisioned": 2, "retired": 2, "finalized": 1, "buckets": 0}


class TestGauges:
    def test_emit_pool_gauges_maps_counts(self, monkeypatch):
        monkeypatch.setattr(
            "engine.services.bucket_state_counts",
            lambda bucket_id: {"ready": 2, "provisioning": 1, "unhealthy": 0, "claimed": 3},
        )
        published: list = []
        monkeypatch.setattr("shared.warm_pool.metrics.emit_gauges", lambda snaps: published.append(snaps) or True)
        wpr._emit_pool_gauges(_ENABLED)
        assert len(published) == 1
        snap = published[0][0]
        assert snap.bucket_id == "gce-polaris"
        assert snap.ready == 2
        assert snap.claimed == 3


@pytest.mark.django_db
class TestManagedUserAndIdentity:
    def test_create_managed_warm_user_is_inactive_and_marked(self):
        user = wpr.create_managed_warm_user()
        assert user.is_active is False
        assert user.email.endswith("@warm-pool.invalid")

    def test_delete_managed_warm_user_removes_marked(self):
        from django.contrib.auth import get_user_model

        user = wpr.create_managed_warm_user()
        pk = user.pk
        wpr._delete_managed_warm_user(user)
        assert not get_user_model().objects.filter(pk=pk).exists()

    def test_delete_managed_warm_user_skips_unmarked(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(username="real@example.com", email="real@example.com")
        wpr._delete_managed_warm_user(user)
        assert get_user_model().objects.filter(pk=user.pk).exists()

    def test_delete_managed_warm_user_none_is_noop(self):
        wpr._delete_managed_warm_user(None)  # must not raise

    def test_policy_fingerprint_is_deterministic(self):
        bucket = _ENABLED.buckets[0]
        first = wpr._policy_fingerprint(_ENABLED, bucket)
        second = wpr._policy_fingerprint(_ENABLED, bucket)
        assert first == second
        assert first.startswith("sha256:")

    def test_resolve_bucket_identity_found_and_missing(self):
        from django.contrib.auth import get_user_model

        from cms.models import RaesPackageSource

        bucket = _ENABLED.buckets[0]
        assert wpr._resolve_bucket_identity(bucket) is None
        registrar = get_user_model().objects.create_user(username="registrar@example.com")
        RaesPackageSource.objects.create(
            scenario_id="polaris",
            contract_kind="raes",
            contract_profile="shifter",
            package_ref="tests/packs/polaris",
            package_version="1.0.0",
            package_digest="sha256:" + "a" * 64,
            lock_digest="sha256:" + "b" * 64,
            conformance_status="passed",
            registered_by=registrar,
        )
        assert wpr._resolve_bucket_identity(bucket) == ("sha256:" + "a" * 64, "sha256:" + "b" * 64)


@pytest.mark.django_db
class TestProvisionWarmGeneration:
    def _patch_dispatch_seams(self, monkeypatch):
        monkeypatch.setattr("cms.services._raes_range_create._load_raes_source_or_raise", lambda scenario: object())
        monkeypatch.setattr("cms.services._range_workspace.resolve_launch_workspace", lambda user, uuid: 1)
        monkeypatch.setattr("cms.services._range_workspace.admit_workspace_launch", lambda **kwargs: None)
        monkeypatch.setattr(
            "cms.services._range_launch_common._reserve_active_range_slot",
            lambda *a, **k: (uuid4(), None, None, "status-quo"),
        )
        monkeypatch.setattr("cms.services._raes_range_create._dispatch_raes_package", lambda *a, **k: None)
        monkeypatch.setattr("cms.services._raes_range_create._audit_raes_range_provision", lambda *a, **k: None)

    def test_backend_not_warm_capable_skips_without_managed_user(self, monkeypatch):
        from django.contrib.auth import get_user_model

        monkeypatch.setattr(
            "cms.services._range_backend_admission.assert_backend_admitted", lambda purpose, source: None
        )
        before = get_user_model().objects.count()
        assert wpr._provision_warm_generation(_ENABLED.buckets[0], _ENABLED, "digest") is False
        # Admission runs before any managed user is created: no leak.
        assert get_user_model().objects.count() == before

    def test_happy_path_dispatches_and_records_ledger(self, monkeypatch):
        from engine.models import WarmRangeGeneration

        monkeypatch.setattr(
            "cms.services._range_backend_admission.assert_backend_admitted",
            lambda purpose, source: SimpleNamespace(backend="gce"),
        )
        self._patch_dispatch_seams(monkeypatch)
        monkeypatch.setattr(
            "engine.services.admit_warm_generation_capacity",
            lambda *, scope_ref, draw_key: SimpleNamespace(blocking=False),
        )
        assert wpr._provision_warm_generation(_ENABLED.buckets[0], _ENABLED, "digest") is True
        gen = WarmRangeGeneration.objects.get(bucket_id="gce-polaris")
        assert gen.state == WarmRangeGeneration.State.PROVISIONING
        assert gen.compatibility_digest == "digest"

    def test_capacity_refusal_abandons_preparation(self, monkeypatch):
        from django.contrib.auth import get_user_model

        from engine.models import WarmRangeGeneration

        monkeypatch.setattr(
            "cms.services._range_backend_admission.assert_backend_admitted",
            lambda purpose, source: SimpleNamespace(backend="gce"),
        )
        self._patch_dispatch_seams(monkeypatch)
        monkeypatch.setattr(
            "engine.services.admit_warm_generation_capacity",
            lambda *, scope_ref, draw_key: SimpleNamespace(blocking=True),
        )
        before_users = get_user_model().objects.count()
        assert wpr._provision_warm_generation(_ENABLED.buckets[0], _ENABLED, "digest") is False
        # The abandoned preparation retires its ledger row and deletes the managed user.
        gen = WarmRangeGeneration.objects.get(bucket_id="gce-polaris")
        assert gen.state == WarmRangeGeneration.State.RETIRING
        assert get_user_model().objects.count() == before_users
