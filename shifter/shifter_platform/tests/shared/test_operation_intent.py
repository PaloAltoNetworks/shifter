"""Contract tests for the canonical public-operation intent projection (#2086, ADR-063-R2).

The retry-safe public API binds a caller retry key to the *complete* immutable
intent of an operation. These tests pin the digest's order-independence, its
fail-closed rejection of non-finite / non-JSON shapes before hashing, and the
intent-projection version being distinct and stable.
"""

from __future__ import annotations

import pytest

from shared.operation_intent import (
    INTENT_PROJECTION_VERSION,
    IntentProjectionError,
    canonical_intent_digest,
    validate_intent_projection,
)


def _projection(**overrides):
    base = {
        "intent_projection_version": INTENT_PROJECTION_VERSION,
        "action": "raes-range:provision",
        "actor": {"user_id": 7, "workspace_id": 3},
        "admission": {"source": "catalog", "purpose": "live_fire", "backend": "gce"},
        "egress_mode": "restricted",
        "compiled_plan": {"nodes": [{"name": "a"}, {"name": "b"}], "version": "1"},
        "artifact_bindings": [{"artifact_id": "x", "digest": "sha256:aa"}],
    }
    base.update(overrides)
    return base


def test_version_is_a_stable_string():
    assert isinstance(INTENT_PROJECTION_VERSION, str)
    assert INTENT_PROJECTION_VERSION == "1"


def test_digest_is_key_order_independent():
    a = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}
    b = {"a": 1, "nested": {"x": 1, "y": 2}, "b": 2}
    assert canonical_intent_digest(a) == canonical_intent_digest(b)


def test_digest_has_sha256_prefix():
    assert canonical_intent_digest(_projection()).startswith("sha256:")


def test_changed_bound_component_changes_digest():
    base = _projection()
    for field, changed in (
        ("action", "raes-range:destroy"),
        ("actor", {"user_id": 7, "workspace_id": 4}),
        ("admission", {"source": "catalog", "purpose": "training", "backend": "gce"}),
        ("egress_mode", "open"),
        ("compiled_plan", {"nodes": [{"name": "a"}], "version": "1"}),
        ("artifact_bindings", [{"artifact_id": "x", "digest": "sha256:bb"}]),
    ):
        assert canonical_intent_digest(base) != canonical_intent_digest(_projection(**{field: changed})), field


def test_non_finite_float_rejected_before_hashing():
    for bad in (float("nan"), float("inf"), float("-inf")):
        projection = _projection(lease={"seconds": bad})
        with pytest.raises(IntentProjectionError):
            canonical_intent_digest(projection)


def test_nested_non_finite_rejected():
    projection = _projection(compiled_plan={"nodes": [{"cpu": float("inf")}]})
    with pytest.raises(IntentProjectionError):
        canonical_intent_digest(projection)


def test_unsupported_type_rejected():
    projection = _projection(actor={"roles": {"admin", "user"}})
    with pytest.raises(IntentProjectionError):
        canonical_intent_digest(projection)


def test_non_dict_projection_rejected():
    with pytest.raises(IntentProjectionError):
        validate_intent_projection(["not", "an", "object"])


def test_non_string_object_key_rejected():
    with pytest.raises(IntentProjectionError):
        canonical_intent_digest({"ok": {1: "int-key"}})
