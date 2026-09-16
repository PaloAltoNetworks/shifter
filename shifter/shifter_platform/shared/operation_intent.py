"""Canonical public-operation intent projection and digest (#2086, ADR-063-R2).

The retry-safe public API binds a caller retry key to the *complete* immutable
intent of an operation -- the validated action and target, actor and workspace
scope, admission, egress and lease policy, package/lock and producer/contract
versions, the compiled plan, and the selected image/artifact/configuration and
delivery/participant-access bindings -- not merely the dispatch argv. Internal
reuse previously compared only ``argv|operation_id`` (``engine.launch_intents``),
which is precisely why a same-key/different-intent replay could slip past.

This module owns the intent-projection *version* and the canonical digest over a
validated projection. Assembling the projection from the persisted contracts is
the engine/cms layer's job (``engine.operation_inputs``); it is not re-modelled
here. Like ``shared.operation_envelope`` the digest is a pure function so it can
be exercised without Django, and there is exactly one native error type -- no
parallel exception hierarchy.
"""

from __future__ import annotations

import math
from typing import Any

from shared.exceptions import ValidationError as IntentProjectionError
from shared.operation_envelope import canonical_payload_digest

__all__ = [
    "INTENT_PROJECTION_VERSION",
    "IntentProjectionError",
    "canonical_intent_digest",
    "validate_intent_projection",
]

# The intent-projection version is deliberately distinct from the HTTP major, the
# RAES producer, and the worker-envelope contract versions (ADR-063-R2). Bump it
# whenever the *set of bound components* changes so a retained binding never
# silently compares against a differently shaped projection.
INTENT_PROJECTION_VERSION = "1"

ProjectionDict = dict[str, Any]


def _reject_invalid(value: object, path: str) -> None:
    """Fail closed on non-finite numbers and non-JSON shapes before hashing.

    ``canonical_payload_digest`` serializes with ``json.dumps``, which would emit
    ``NaN``/``Infinity`` (invalid JSON) and silently accept a stray container
    type. Validating here keeps an ambiguous intent from ever producing a digest
    that two sides could disagree on.
    """
    # ``bool`` is an ``int`` subclass; both are safe scalars, as are ``str`` and
    # ``None``. Check ``bool`` explicitly only for clarity of intent.
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IntentProjectionError(f"{path} must be a finite number")
    elif isinstance(value, dict):
        _reject_invalid_mapping(value, path)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_invalid(item, f"{path}[{index}]")
    else:
        raise IntentProjectionError(f"{path} has an unsupported type: {type(value).__name__}")


def _reject_invalid_mapping(mapping: dict[object, object], path: str) -> None:
    """Reject non-string keys and recurse into values of a mapping."""
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise IntentProjectionError(f"{path} object keys must be strings")
        _reject_invalid(item, f"{path}.{key}")


def validate_intent_projection(projection: object) -> ProjectionDict:
    """Return the projection when it is a hashable JSON object, else fail closed."""
    if not isinstance(projection, dict):
        raise IntentProjectionError("intent projection must be an object")
    _reject_invalid(projection, "intent projection")
    return projection


def canonical_intent_digest(projection: ProjectionDict) -> str:
    """Return the order-independent digest of a validated intent projection.

    Two callers submitting the same admitted intent -- in any key order -- get an
    equal digest and converge on one binding; any change to a bound component
    yields a different digest and conflicts before reservation or effects
    (ADR-063-R2). Mirrors ``canonical_payload_digest`` so engine and API agree
    byte-for-byte.
    """
    validate_intent_projection(projection)
    return canonical_payload_digest(projection)
