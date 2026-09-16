"""Tests for ``shared.warm_pool.compatibility`` (#28).

The compatibility digest is the authoritative warm-pool claim proof: a ready
generation's digest must equal the requested launch's digest. These tests pin:

- determinism / key-order independence (equal dimensions -> equal digest);
- sensitivity (any changed dimension -> different digest), including the optional
  posture fields;
- fail-closed on a missing required dimension or a non-string value;
- the schema tag participates so a future dimension-set change cannot collide.
"""

from __future__ import annotations

import dataclasses

import pytest

from shared.warm_pool.compatibility import (
    COMPATIBILITY_SCHEMA,
    CompatibilityKey,
    WarmPoolCompatibilityError,
    compatibility_digest,
)


def _key(**overrides) -> CompatibilityKey:
    base = {
        "backend": "gce",
        "instantiation_purpose": "live-fire",
        "range_source": "mission-control",
        "workspace_isolation_class": "personal",
        "egress_mode": "status-quo",
        "scenario": "polaris",
        "package_digest": "sha256:aaa",
        "lock_digest": "sha256:bbb",
    }
    base.update(overrides)
    return CompatibilityKey(**base)


class TestDeterminism:
    def test_equal_keys_equal_digest(self):
        first = compatibility_digest(_key())
        second = compatibility_digest(_key())
        assert first == second

    def test_digest_is_prefixed_sha256(self):
        assert compatibility_digest(_key()).startswith("sha256:")

    def test_field_construction_order_irrelevant(self):
        # dataclass fields are positional; build via kwargs in different orders.
        a = _key(backend="gce", lock_digest="sha256:bbb")
        b = _key(lock_digest="sha256:bbb", backend="gce")
        assert compatibility_digest(a) == compatibility_digest(b)


class TestSensitivity:
    @pytest.mark.parametrize(
        "field",
        [f.name for f in dataclasses.fields(CompatibilityKey)],
    )
    def test_changing_any_dimension_changes_digest(self, field):
        baseline = compatibility_digest(_key())
        changed = compatibility_digest(_key(**{field: "sha256:CHANGED-value"}))
        assert changed != baseline

    def test_posture_change_differs(self):
        default_egress = compatibility_digest(_key(egress_mode="status-quo"))
        other_egress = compatibility_digest(_key(egress_mode="deny-all"))
        assert default_egress != other_egress


class TestFailClosed:
    @pytest.mark.parametrize("field", ["backend", "range_source", "package_digest", "lock_digest", "scenario"])
    def test_missing_required_dimension_rejected(self, field):
        key = _key(**{field: ""})
        with pytest.raises(WarmPoolCompatibilityError) as exc:
            compatibility_digest(key)
        assert field in str(exc.value)

    def test_non_string_dimension_rejected(self):
        key = _key(egress_mode=123)  # type: ignore[arg-type]
        with pytest.raises(WarmPoolCompatibilityError):
            compatibility_digest(key)


class TestSchemaTag:
    def test_schema_tag_in_normalized_payload(self):
        assert _key().normalized()["__schema__"] == COMPATIBILITY_SCHEMA
