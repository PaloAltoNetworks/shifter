"""Tests for ``shared.warm_pool.policy`` (#28): runtime parser + narrowing resolver.

Pins: disabled-by-default parse; fail-closed on malformed projection; and the
core security property of the override resolver -- an override may only *narrow*
deployment-owned limits, and any widening (raise a max, add/unknown bucket, raise
concurrency/cost) is rejected, never clamped.
"""

from __future__ import annotations

import json

import pytest

from shared.warm_pool.policy import (
    WarmPoolOverride,
    WarmPoolPolicyError,
    load_policy_json,
    resolve_effective_policy,
)


def _projection(**overrides):
    base = {
        "enabled": True,
        "replenish_interval_seconds": 300,
        "replenish_concurrency": 4,
        "max_total_ready": 10,
        "scale_down": "oldest-first",
        "replacement": "destroy-and-replace",
        "buckets": [
            {
                "id": "gce-polaris",
                "backend": "gce",
                "scenario": "polaris",
                "capacity_partition": "default",
                "target": 3,
                "minimum": 1,
                "maximum": 5,
                "idle_ttl_seconds": 3600,
            }
        ],
    }
    base.update(overrides)
    return json.dumps(base)


class TestParse:
    def test_empty_is_disabled(self):
        policy = load_policy_json("")
        assert policy.enabled is False
        assert policy.is_active() is False

    def test_valid_projection(self):
        policy = load_policy_json(_projection())
        assert policy.is_active() is True
        assert policy.bucket("gce-polaris").maximum == 5

    def test_invalid_json_rejected(self):
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json("{not json")

    def test_bad_ordering_rejected(self):
        projection = _projection(
            buckets=[
                {
                    "id": "b",
                    "backend": "gce",
                    "scenario": "s",
                    "capacity_partition": "default",
                    "target": 9,
                    "minimum": 1,
                    "maximum": 5,
                    "idle_ttl_seconds": 60,
                }
            ]
        )
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json(projection)

    def test_duplicate_bucket_ids_rejected(self):
        dup = [
            {
                "id": "b",
                "backend": "gce",
                "scenario": "s",
                "capacity_partition": "default",
                "target": 1,
                "minimum": 0,
                "maximum": 2,
                "idle_ttl_seconds": 60,
            }
        ] * 2
        projection = _projection(buckets=dup)
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json(projection)

    def test_unknown_scale_down_rejected(self):
        projection = _projection(scale_down="random")
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json(projection)

    def test_unknown_replacement_rejected(self):
        projection = _projection(replacement="melt-it")
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json(projection)

    def test_non_object_projection_rejected(self):
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json("[1, 2, 3]")

    def test_negative_max_total_ready_rejected(self):
        projection = _projection(max_total_ready=-1)
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json(projection)

    def test_bad_image_set_rejected(self):
        projection = _projection(
            buckets=[
                {
                    "id": "b",
                    "backend": "gce",
                    "scenario": "s",
                    "capacity_partition": "default",
                    "target": 1,
                    "minimum": 0,
                    "maximum": 2,
                    "idle_ttl_seconds": 60,
                    "image_set": "not-a-list",
                }
            ]
        )
        with pytest.raises(WarmPoolPolicyError):
            load_policy_json(projection)


class TestResolveNarrowing:
    def test_no_override_returns_deployment(self):
        dep = load_policy_json(_projection())
        assert resolve_effective_policy(dep, None) is dep
        assert resolve_effective_policy(dep, WarmPoolOverride()) is dep

    def test_disable_forces_off(self):
        dep = load_policy_json(_projection())
        eff = resolve_effective_policy(dep, WarmPoolOverride(disable=True))
        assert eff.enabled is False
        assert eff.buckets == ()

    def test_restrict_buckets_subset(self):
        dep = load_policy_json(_projection())
        eff = resolve_effective_policy(dep, WarmPoolOverride(bucket_ids=()))
        assert eff.buckets == ()

    def test_unknown_bucket_rejected(self):
        dep = load_policy_json(_projection())
        override = WarmPoolOverride(bucket_ids=("nope",))
        with pytest.raises(WarmPoolPolicyError):
            resolve_effective_policy(dep, override)

    def test_narrow_concurrency_down_ok(self):
        dep = load_policy_json(_projection())
        eff = resolve_effective_policy(dep, WarmPoolOverride(replenish_concurrency=1))
        assert eff.replenish_concurrency == 1

    def test_widen_concurrency_rejected(self):
        dep = load_policy_json(_projection())
        override = WarmPoolOverride(replenish_concurrency=99)
        with pytest.raises(WarmPoolPolicyError) as exc:
            resolve_effective_policy(dep, override)
        assert "may not exceed" in str(exc.value)

    def test_narrow_max_total_ready_ok(self):
        dep = load_policy_json(_projection())
        eff = resolve_effective_policy(dep, WarmPoolOverride(max_total_ready=5))
        assert eff.max_total_ready == 5

    def test_narrow_cost_ceiling_ok(self):
        dep = load_policy_json(_projection(cost_ceiling=100.0))
        eff = resolve_effective_policy(dep, WarmPoolOverride(cost_ceiling=25.0))
        assert eff.cost_ceiling == 25.0

    def test_narrow_bucket_cap_ok(self):
        dep = load_policy_json(_projection())
        eff = resolve_effective_policy(dep, WarmPoolOverride(bucket_caps={"gce-polaris": {"maximum": 2, "target": 2}}))
        assert eff.bucket("gce-polaris").maximum == 2

    def test_narrow_bucket_idle_ttl_ok(self):
        dep = load_policy_json(_projection())
        eff = resolve_effective_policy(dep, WarmPoolOverride(bucket_caps={"gce-polaris": {"idle_ttl_seconds": 60}}))
        assert eff.bucket("gce-polaris").idle_ttl_seconds == 60

    def test_widen_bucket_cap_rejected(self):
        dep = load_policy_json(_projection())
        override = WarmPoolOverride(bucket_caps={"gce-polaris": {"maximum": 99}})
        with pytest.raises(WarmPoolPolicyError):
            resolve_effective_policy(dep, override)

    def test_override_cannot_set_unknown_bucket_field(self):
        dep = load_policy_json(_projection())
        override = WarmPoolOverride(bucket_caps={"gce-polaris": {"backend": 1}})
        with pytest.raises(WarmPoolPolicyError):
            resolve_effective_policy(dep, override)

    def test_caps_for_unknown_bucket_rejected(self):
        dep = load_policy_json(_projection())
        override = WarmPoolOverride(bucket_caps={"ghost": {"maximum": 1}})
        with pytest.raises(WarmPoolPolicyError):
            resolve_effective_policy(dep, override)

    def test_widen_cost_ceiling_rejected(self):
        dep = load_policy_json(_projection(cost_ceiling=100.0))
        override = WarmPoolOverride(cost_ceiling=999.0)
        with pytest.raises(WarmPoolPolicyError):
            resolve_effective_policy(dep, override)
