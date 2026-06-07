"""Tests for ``installation.range_egress`` (PLAT-220).

The platform-level range egress policy is validated at the installation package
boundary so AWS and GCP backend bundles share a single source of truth for what
counts as a valid CIDR allowlist. These tests pin the public contract:

- Three modes: ``status-quo`` (default, omit allowlist), ``deny-all``, ``allowlist``.
- ``allowlist`` requires at least one CIDR; ``deny-all`` / ``status-quo`` must not
  carry CIDR entries.
- Default-route CIDRs (``0.0.0.0/0``, ``::/0``) are rejected: allow-all is a
  separate mode (out of scope for PLAT-220), not a sentinel CIDR.
- Each CIDR is canonicalised; host-bit-set inputs and duplicates are rejected.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from installation.range_egress import (
    SETTINGS_KEY,
    RangeEgressMode,
    RangeEgressPolicy,
    validate_settings_block,
)


class TestDefaults:
    def test_omitted_block_defaults_to_status_quo(self):
        policy = RangeEgressPolicy.model_validate({})
        assert policy.mode == RangeEgressMode.STATUS_QUO
        assert policy.allowed_cidrs == []

    def test_status_quo_string_value_accepted(self):
        policy = RangeEgressPolicy.model_validate({"mode": "status-quo"})
        assert policy.mode == RangeEgressMode.STATUS_QUO

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValidationError) as exc:
            RangeEgressPolicy.model_validate({"mode": "allow-all"})
        assert "allow-all" in str(exc.value) or "mode" in str(exc.value)

    def test_extra_keys_forbidden(self):
        with pytest.raises(ValidationError):
            RangeEgressPolicy.model_validate({"mode": "status-quo", "junk": True})


class TestAllowlistMode:
    def test_allowlist_requires_at_least_one_cidr(self):
        with pytest.raises(ValidationError) as exc:
            RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": []})
        assert "allowlist" in str(exc.value)

    def test_allowlist_with_cidrs_accepts(self):
        policy = RangeEgressPolicy.model_validate(
            {"mode": "allowlist", "allowed_cidrs": ["203.0.113.0/24", "198.51.100.42/32"]}
        )
        assert policy.mode == RangeEgressMode.ALLOWLIST
        assert policy.allowed_cidrs == ["203.0.113.0/24", "198.51.100.42/32"]

    def test_allowlist_accepts_ipv6(self):
        policy = RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": ["2001:db8::/32"]})
        assert policy.allowed_cidrs == ["2001:db8::/32"]


class TestModeAllowlistMismatch:
    def test_status_quo_with_cidrs_rejected(self):
        with pytest.raises(ValidationError) as exc:
            RangeEgressPolicy.model_validate({"mode": "status-quo", "allowed_cidrs": ["203.0.113.0/24"]})
        assert "allowlist" in str(exc.value)

    def test_deny_all_with_cidrs_rejected(self):
        with pytest.raises(ValidationError) as exc:
            RangeEgressPolicy.model_validate({"mode": "deny-all", "allowed_cidrs": ["203.0.113.0/24"]})
        assert "allowlist" in str(exc.value)


class TestCidrValidation:
    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-cidr",
            "10.0.0.0",  # no prefix length
            "10.0.0.0/33",  # prefix out of range
            "10.0.0.0/-1",
            " 10.0.0.0/24",  # leading whitespace
            "10.0.0.0/24 ",  # trailing whitespace
            "",
        ],
    )
    def test_malformed_cidrs_rejected(self, bad: str):
        with pytest.raises(ValidationError):
            RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": [bad]})

    @pytest.mark.parametrize("default_route", ["0.0.0.0/0", "::/0"])
    def test_default_route_cidrs_rejected(self, default_route: str):
        with pytest.raises(ValidationError) as exc:
            RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": [default_route]})
        assert "/0" in str(exc.value) or "default route" in str(exc.value)

    def test_host_bits_set_rejected(self):
        # 10.0.0.5/24 has host bits set; the network is 10.0.0.0/24.
        with pytest.raises(ValidationError) as exc:
            RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": ["10.0.0.5/24"]})
        assert "host bits" in str(exc.value) or "10.0.0.0/24" in str(exc.value)

    def test_single_host_32_accepted(self):
        policy = RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": ["8.8.8.8/32"]})
        assert policy.allowed_cidrs == ["8.8.8.8/32"]

    def test_duplicate_cidrs_rejected(self):
        with pytest.raises(ValidationError) as exc:
            RangeEgressPolicy.model_validate(
                {
                    "mode": "allowlist",
                    "allowed_cidrs": ["203.0.113.0/24", "203.0.113.0/24"],
                }
            )
        assert "duplicate" in str(exc.value)

    def test_non_string_cidr_rejected(self):
        with pytest.raises(ValidationError):
            RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": [12345]})


class TestNormalization:
    """The normalized output must be deterministic so downstream backends (AWS
    Network Firewall, GCP VPC firewall) see stable rule definitions across runs."""

    def test_canonical_cidrs_preserved(self):
        policy = RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": ["203.0.113.0/24"]})
        assert policy.allowed_cidrs == ["203.0.113.0/24"]

    def test_dump_round_trip(self):
        original = RangeEgressPolicy.model_validate({"mode": "allowlist", "allowed_cidrs": ["203.0.113.0/24"]})
        as_dict = original.model_dump()
        round_tripped = RangeEgressPolicy.model_validate(as_dict)
        assert round_tripped == original


class TestSettingsBlockWrapper:
    """The loader calls ``validate_settings_block`` after the bundle's own validation
    so the same shape is enforced for AWS and GCP without per-backend duplication."""

    def test_absent_block_is_no_op(self):
        normalized, issues = validate_settings_block({"region": "us-east-2"})
        assert issues == []
        assert normalized == {"region": "us-east-2"}
        assert SETTINGS_KEY not in normalized or normalized[SETTINGS_KEY] is None  # type: ignore[unreachable]

    def test_explicit_status_quo_normalized(self):
        settings = {"region": "us-east-2", "range_egress": {"mode": "status-quo"}}
        normalized, issues = validate_settings_block(settings)
        assert issues == []
        assert normalized["range_egress"] == {"mode": "status-quo", "allowed_cidrs": []}

    def test_allowlist_canonicalised_and_returned(self):
        settings = {
            "range_egress": {
                "mode": "allowlist",
                "allowed_cidrs": ["203.0.113.0/24", "8.8.8.8/32"],
            }
        }
        normalized, issues = validate_settings_block(settings)
        assert issues == []
        assert normalized["range_egress"] == {
            "mode": "allowlist",
            "allowed_cidrs": ["203.0.113.0/24", "8.8.8.8/32"],
        }

    def test_invalid_cidr_emits_anchored_issue(self):
        settings = {"range_egress": {"mode": "allowlist", "allowed_cidrs": ["not-a-cidr"]}}
        _, issues = validate_settings_block(settings)
        assert len(issues) >= 1
        assert any(issue.path.startswith("settings.range_egress.allowed_cidrs") for issue in issues)
        # Operator-facing message must include the bad value's shape problem.
        assert any("not-a-cidr" in issue.message for issue in issues)

    def test_non_mapping_block_emits_top_level_issue(self):
        _, issues = validate_settings_block({"range_egress": ["not", "a", "mapping"]})
        assert len(issues) == 1
        assert issues[0].path == "settings.range_egress"

    def test_default_route_anchored_under_allowed_cidrs(self):
        settings = {"range_egress": {"mode": "allowlist", "allowed_cidrs": ["0.0.0.0/0"]}}
        _, issues = validate_settings_block(settings)
        assert any(issue.path.startswith("settings.range_egress.allowed_cidrs") for issue in issues)
