"""Tests for ``installation.warm_pool`` (#28).

The warm-pool policy is validated at the installation package boundary so AWS and
GCP bundles share one source of truth. These tests pin the public contract:

- Disabled by default; an omitted block or ``enabled=false`` preserves cold
  provisioning, and declaring buckets while disabled is rejected as an operator
  error.
- Enabled requires at least one bucket and bounded cadence/concurrency.
- Every bucket enforces ``0 <= minimum <= target <= maximum`` and a finite idle
  TTL; bucket ids are unique across the policy.
- The model is closed (``extra='forbid'``): unknown keys, unknown backends, and
  unknown strategies fail at load. No provider creds/overrides/dicts are accepted.
- ``validate_settings_block`` anchors issues under ``settings.warm_pool`` and
  normalizes a valid block; ``runtime_projection`` round-trips.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from installation.warm_pool import (
    SETTINGS_KEY,
    WarmPoolBackend,
    WarmPoolPolicy,
    WarmPoolScaleDownStrategy,
    runtime_projection,
    validate_settings_block,
)


def _bucket(**overrides):
    base = {
        "id": "gce-polaris",
        "backend": "gce",
        "scenario": "polaris",
        "capacity_partition": "default",
        "target": 2,
        "minimum": 1,
        "maximum": 4,
    }
    base.update(overrides)
    return base


def _enabled_policy(**overrides):
    base = {"enabled": True, "buckets": [_bucket()]}
    base.update(overrides)
    return base


class TestDefaults:
    def test_omitted_block_is_disabled(self):
        policy = WarmPoolPolicy.model_validate({})
        assert policy.enabled is False
        assert policy.buckets == []
        assert policy.is_active() is False

    def test_disabled_with_buckets_rejected(self):
        data = {"enabled": False, "buckets": [_bucket()]}
        with pytest.raises(ValidationError) as exc:
            WarmPoolPolicy.model_validate(data)
        assert "disabled" in str(exc.value)

    def test_extra_keys_forbidden(self):
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate({"enabled": False, "junk": True})

    def test_no_arbitrary_extension_dict_on_bucket(self):
        data = _enabled_policy(buckets=[_bucket(provider_overrides={"x": 1})])
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate(data)


class TestEnabledInvariants:
    def test_enabled_requires_buckets(self):
        with pytest.raises(ValidationError) as exc:
            WarmPoolPolicy.model_validate({"enabled": True, "buckets": []})
        assert "no buckets" in str(exc.value)

    def test_enabled_with_bucket_is_active(self):
        policy = WarmPoolPolicy.model_validate(_enabled_policy())
        assert policy.is_active() is True
        assert policy.buckets[0].backend == WarmPoolBackend.GCE
        assert policy.scale_down == WarmPoolScaleDownStrategy.OLDEST_FIRST

    def test_duplicate_bucket_ids_rejected(self):
        data = _enabled_policy(buckets=[_bucket(), _bucket(scenario="other")])
        with pytest.raises(ValidationError) as exc:
            WarmPoolPolicy.model_validate(data)
        assert "duplicate bucket id" in str(exc.value)

    @pytest.mark.parametrize("interval", [0, 100_000])
    def test_replenish_interval_bounds(self, interval):
        data = _enabled_policy(replenish_interval_seconds=interval)
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate(data)

    @pytest.mark.parametrize("concurrency", [0, 1000])
    def test_replenish_concurrency_bounds(self, concurrency):
        data = _enabled_policy(replenish_concurrency=concurrency)
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate(data)

    def test_max_total_ready_smaller_than_bucket_target_rejected(self):
        data = _enabled_policy(max_total_ready=1, buckets=[_bucket(target=3, maximum=3)])
        with pytest.raises(ValidationError) as exc:
            WarmPoolPolicy.model_validate(data)
        assert "starve" in str(exc.value)

    def test_max_total_ready_over_ceiling_rejected(self):
        data = _enabled_policy(max_total_ready=100_000)
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate(data)


class TestBucketInvariants:
    @pytest.mark.parametrize(
        "minimum,target,maximum",
        [(2, 1, 4), (0, 3, 2), (-1, 0, 1)],
    )
    def test_ordering_enforced(self, minimum, target, maximum):
        data = _enabled_policy(buckets=[_bucket(minimum=minimum, target=target, maximum=maximum)])
        with pytest.raises(ValidationError) as exc:
            WarmPoolPolicy.model_validate(data)
        assert "minimum <= target <= maximum" in str(exc.value)

    @pytest.mark.parametrize("ttl", [0, 10_000_000])
    def test_idle_ttl_bounds(self, ttl):
        data = _enabled_policy(buckets=[_bucket(idle_ttl_seconds=ttl)])
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate(data)

    def test_unknown_backend_rejected(self):
        data = _enabled_policy(buckets=[_bucket(backend="azure")])
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate(data)

    def test_duplicate_image_set_rejected(self):
        data = _enabled_policy(buckets=[_bucket(image_set=["a", "a"])])
        with pytest.raises(ValidationError) as exc:
            WarmPoolPolicy.model_validate(data)
        assert "image_set" in str(exc.value)

    def test_optional_narrowing_dimensions_accepted(self):
        policy = WarmPoolPolicy.model_validate(
            _enabled_policy(buckets=[_bucket(region="us-east1", access_mode="vpn", image_set=["kali", "dc"])])
        )
        bucket = policy.buckets[0]
        assert bucket.region == "us-east1"
        assert bucket.access_mode == "vpn"
        assert bucket.image_set == ["kali", "dc"]

    def test_negative_cost_ceiling_rejected(self):
        data = _enabled_policy(buckets=[_bucket(cost_ceiling=-1.0)])
        with pytest.raises(ValidationError):
            WarmPoolPolicy.model_validate(data)


class TestSettingsBlock:
    def test_absent_block_returns_input_unchanged(self):
        settings = {"other": 1}
        normalized, issues = validate_settings_block(settings)
        assert issues == []
        assert normalized == settings

    def test_valid_block_normalized(self):
        settings = {SETTINGS_KEY: _enabled_policy()}
        normalized, issues = validate_settings_block(settings)
        assert issues == []
        assert normalized[SETTINGS_KEY]["enabled"] is True
        assert normalized[SETTINGS_KEY]["buckets"][0]["backend"] == "gce"

    def test_non_mapping_block_flagged(self):
        _normalized, issues = validate_settings_block({SETTINGS_KEY: ["nope"]})
        assert issues
        assert issues[0].path == f"settings.{SETTINGS_KEY}"

    def test_invalid_block_issues_anchored(self):
        _, issues = validate_settings_block({SETTINGS_KEY: {"enabled": True, "buckets": []}})
        assert issues
        assert all(issue.path.startswith(f"settings.{SETTINGS_KEY}") for issue in issues)


class TestRuntimeProjection:
    def test_projection_round_trips(self):
        policy = WarmPoolPolicy.model_validate(_enabled_policy())
        projection = runtime_projection(policy)
        # The projection is a pure JSON shape re-validatable back to the model.
        assert WarmPoolPolicy.model_validate(projection).is_active() is True
        assert projection["buckets"][0]["id"] == "gce-polaris"


class TestRenderWarmPoolEnv:
    def test_enabled_example_renders_policy_json(self, examples_dir):
        from installation.loader import load_root_config
        from installation.render import render_warm_pool_env

        rendered = render_warm_pool_env(load_root_config(examples_dir / "gcp.yaml"))
        assert "WARM_POOL_POLICY_JSON=" in rendered
        assert '"enabled":true' in rendered
        assert "gce-polaris" in rendered

    def test_absent_block_renders_disabled(self, examples_dir):
        from installation.loader import load_root_config
        from installation.render import render_warm_pool_env

        # The AWS example ships no warm_pool block: it must render the disabled policy.
        rendered = render_warm_pool_env(load_root_config(examples_dir / "aws.yaml"))
        assert "WARM_POOL_POLICY_JSON=" in rendered
        assert '"enabled":false' in rendered
