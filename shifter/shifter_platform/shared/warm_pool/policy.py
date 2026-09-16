"""Runtime warm-pool policy model and effective-policy resolver (#28).

``installation.warm_pool`` is the *install-time* validation boundary (pydantic,
inside the installation package, rendered from ``shifter.yaml``). The runtime
(portal + warm reconciler) cannot import that package, so this module is the
Django-free, stdlib runtime parser for the same policy shape -- mirroring how
``shared.capacity.catalog`` is the runtime capacity model and ``shared.raes.operation_input``
mirrors the installation backend vocabulary. The JSON it parses is exactly
``installation.warm_pool.WarmPoolPolicy.runtime_projection`` output, already
validated at install time; this parser fails closed on anything malformed rather
than trusting the projection blindly.

It also owns the pure ``deployment policy + optional narrowing override -> effective
policy`` resolver (preflight #28): an event/workspace override may only *narrow*
deployment-owned limits -- disable the pool, reduce counts/concurrency/ceilings/
lifetime, or restrict eligible buckets. It may never raise a maximum, add a bucket,
change a backend/partition, or weaken isolation. Widening is rejected, never
clamped, so a misconfigured override fails loudly instead of silently exceeding a
deployment ceiling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import cast

__all__ = [
    "WarmPoolBucketPolicy",
    "WarmPoolOverride",
    "WarmPoolPolicyError",
    "WarmPoolRuntimePolicy",
    "load_policy_json",
    "resolve_effective_policy",
]

_SCALE_DOWN = frozenset({"oldest-first", "newest-first"})
_REPLACEMENT = frozenset({"destroy-and-replace", "destroy-only"})


class WarmPoolPolicyError(Exception):
    """The warm-pool policy projection or override is malformed or widens a limit."""


def _require(condition: bool, message: str) -> None:
    """Raise :class:`WarmPoolPolicyError` with ``message`` unless ``condition`` holds."""
    if not condition:
        raise WarmPoolPolicyError(message)


def _require_int(value: object, field_name: str, *, minimum: int = 0) -> int:
    """Return ``value`` as an int, failing closed unless it is an int ``>= minimum``."""
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise WarmPoolPolicyError(f"{field_name} must be an int >= {minimum}")
    return value


def _optional_float(value: object, field_name: str) -> float | None:
    """Return ``value`` as a non-negative float, or None; fail closed otherwise."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise WarmPoolPolicyError(f"{field_name} must be a non-negative number or null")
    return float(value)


@dataclass(frozen=True)
class WarmPoolBucketPolicy:
    """One compatibility class the pool maintains ready (runtime view)."""

    id: str
    backend: str
    scenario: str
    capacity_partition: str
    target: int
    minimum: int
    maximum: int
    idle_ttl_seconds: int
    region: str | None = None
    access_mode: str | None = None
    image_set: tuple[str, ...] = ()
    cost_ceiling: float | None = None

    def __post_init__(self) -> None:
        _require(bool(self.id), "bucket id must be non-empty")
        _require(0 <= self.minimum <= self.target <= self.maximum, f"bucket {self.id}: 0<=minimum<=target<=maximum")
        _require(self.idle_ttl_seconds > 0, f"bucket {self.id}: idle_ttl_seconds must be positive")


@dataclass(frozen=True)
class WarmPoolRuntimePolicy:
    """The deployment warm-pool policy as evaluated at runtime."""

    enabled: bool = False
    replenish_interval_seconds: int = 300
    replenish_concurrency: int = 1
    max_total_ready: int = 0
    cost_ceiling: float | None = None
    scale_down: str = "oldest-first"
    replacement: str = "destroy-and-replace"
    buckets: tuple[WarmPoolBucketPolicy, ...] = ()

    def is_active(self) -> bool:
        """Return True when the pool should be reconciled and claims attempted."""
        return self.enabled and bool(self.buckets)

    def bucket(self, bucket_id: str) -> WarmPoolBucketPolicy | None:
        """Return the bucket with ``bucket_id``, or None."""
        for bucket in self.buckets:
            if bucket.id == bucket_id:
                return bucket
        return None


def _parse_bucket(raw: object) -> WarmPoolBucketPolicy:
    """Parse one raw bucket object into a validated :class:`WarmPoolBucketPolicy`."""
    if not isinstance(raw, dict):
        raise WarmPoolPolicyError("each bucket must be an object")
    image_set = raw.get("image_set", [])
    if not isinstance(image_set, list) or not all(isinstance(x, str) for x in image_set):
        raise WarmPoolPolicyError("bucket image_set must be a list of strings")
    return WarmPoolBucketPolicy(
        id=str(raw.get("id", "")),
        backend=str(raw.get("backend", "")),
        scenario=str(raw.get("scenario", "")),
        capacity_partition=str(raw.get("capacity_partition", "")),
        target=_require_int(raw.get("target", 0), "bucket target"),
        minimum=_require_int(raw.get("minimum", 0), "bucket minimum"),
        maximum=_require_int(raw.get("maximum", 0), "bucket maximum"),
        idle_ttl_seconds=_require_int(raw.get("idle_ttl_seconds", 3600), "bucket idle_ttl_seconds", minimum=1),
        region=raw.get("region"),
        access_mode=raw.get("access_mode"),
        image_set=tuple(image_set),
        cost_ceiling=_optional_float(raw.get("cost_ceiling"), "bucket cost_ceiling"),
    )


def load_policy_json(raw: str | None) -> WarmPoolRuntimePolicy:
    """Parse the projected warm-pool policy JSON, failing closed on malformed input.

    An empty/absent value is the safe default: a disabled pool.
    """
    text = (raw or "").strip()
    if not text:
        return WarmPoolRuntimePolicy()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WarmPoolPolicyError(f"warm-pool policy is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WarmPoolPolicyError("warm-pool policy must be a JSON object")
    scale_down = str(data.get("scale_down", "oldest-first"))
    replacement = str(data.get("replacement", "destroy-and-replace"))
    _require(scale_down in _SCALE_DOWN, f"scale_down must be one of {sorted(_SCALE_DOWN)}")
    _require(replacement in _REPLACEMENT, f"replacement must be one of {sorted(_REPLACEMENT)}")
    buckets = tuple(_parse_bucket(b) for b in data.get("buckets", []))
    ids = [b.id for b in buckets]
    _require(len(set(ids)) == len(ids), "duplicate bucket id(s) in warm-pool policy")
    return WarmPoolRuntimePolicy(
        enabled=bool(data.get("enabled", False)),
        replenish_interval_seconds=_require_int(
            data.get("replenish_interval_seconds", 300), "replenish_interval_seconds", minimum=1
        ),
        replenish_concurrency=_require_int(data.get("replenish_concurrency", 1), "replenish_concurrency", minimum=1),
        max_total_ready=_require_int(data.get("max_total_ready", 0), "max_total_ready"),
        cost_ceiling=_optional_float(data.get("cost_ceiling"), "cost_ceiling"),
        scale_down=scale_down,
        replacement=replacement,
        buckets=buckets,
    )


@dataclass(frozen=True)
class WarmPoolOverride:
    """An event/workspace narrowing override. Every field is optional; a set field
    may only narrow the deployment policy.

    ``disable`` forces the pool off. ``bucket_ids`` restricts the effective buckets
    to a subset of the deployment buckets. Numeric caps clamp *downward* only:
    a value above the deployment value is rejected, never applied.
    """

    disable: bool = False
    bucket_ids: tuple[str, ...] | None = None
    max_total_ready: int | None = None
    replenish_concurrency: int | None = None
    cost_ceiling: float | None = None
    #: Per-bucket narrowing: bucket_id -> {target/minimum/maximum/idle_ttl_seconds},
    #: each of which may only reduce the deployment bucket's value.
    bucket_caps: dict[str, dict[str, int]] = field(default_factory=dict)


def _narrow_int(deployment: int, override: int | None, name: str) -> int:
    """Return the override value when it narrows ``deployment``; reject any widening."""
    if override is None:
        return deployment
    _require(override >= 0, f"{name} override must be non-negative")
    _require(override <= deployment, f"{name} override {override} may not exceed deployment limit {deployment}")
    return override


def _narrow_bucket(bucket: WarmPoolBucketPolicy, caps: dict[str, int]) -> WarmPoolBucketPolicy:
    """Apply downward-only per-bucket caps, re-validating the narrowed ordering."""
    unknown = sorted(set(caps) - {"target", "minimum", "maximum", "idle_ttl_seconds"})
    _require(not unknown, f"bucket {bucket.id}: override cannot set {unknown}")
    new_maximum = _narrow_int(bucket.maximum, caps.get("maximum"), f"bucket {bucket.id} maximum")
    new_target = _narrow_int(bucket.target, caps.get("target"), f"bucket {bucket.id} target")
    new_minimum = _narrow_int(bucket.minimum, caps.get("minimum"), f"bucket {bucket.id} minimum")
    new_ttl = _narrow_int(bucket.idle_ttl_seconds, caps.get("idle_ttl_seconds"), f"bucket {bucket.id} idle_ttl_seconds")
    _require(new_ttl >= 1, f"bucket {bucket.id}: idle_ttl_seconds override must stay positive")
    # Re-validate the narrowed ordering (a narrow that inverts min<=target<=max fails).
    _require(
        0 <= new_minimum <= new_target <= new_maximum,
        f"bucket {bucket.id}: narrowed values must keep 0<=minimum<=target<=maximum",
    )
    # ``dataclasses.replace`` returns the same dataclass type, but Sonar infers the
    # generic ``DataclassInstance``; the cast restates the concrete return type.
    return cast(
        WarmPoolBucketPolicy,
        replace(bucket, target=new_target, minimum=new_minimum, maximum=new_maximum, idle_ttl_seconds=new_ttl),
    )


def _override_is_noop(override: WarmPoolOverride) -> bool:
    """Return True when ``override`` sets no field and therefore changes nothing."""
    return (
        not override.disable
        and override.bucket_ids is None
        and override.max_total_ready is None
        and override.replenish_concurrency is None
        and override.cost_ceiling is None
        and not override.bucket_caps
    )


def _select_narrowed_buckets(
    deployment: WarmPoolRuntimePolicy, override: WarmPoolOverride, deployment_ids: set[str]
) -> tuple[WarmPoolBucketPolicy, ...]:
    """Restrict to the override's bucket subset (if any) and apply per-bucket caps."""
    selected = deployment.buckets
    if override.bucket_ids is not None:
        unknown = sorted(set(override.bucket_ids) - deployment_ids)
        _require(not unknown, f"override names unknown bucket(s): {unknown}")
        wanted = set(override.bucket_ids)
        selected = tuple(b for b in deployment.buckets if b.id in wanted)
    unknown_caps = sorted(set(override.bucket_caps) - deployment_ids)
    _require(not unknown_caps, f"override caps name unknown bucket(s): {unknown_caps}")
    return tuple(_narrow_bucket(b, override.bucket_caps.get(b.id, {})) for b in selected)


def _resolve_cost_ceiling(deployment: WarmPoolRuntimePolicy, override: WarmPoolOverride) -> float | None:
    """Return the effective cost ceiling; the override may only lower the deployment ceiling."""
    if override.cost_ceiling is None:
        return deployment.cost_ceiling
    _require(override.cost_ceiling >= 0, "cost_ceiling override must be non-negative")
    if deployment.cost_ceiling is not None:
        _require(
            override.cost_ceiling <= deployment.cost_ceiling,
            "cost_ceiling override may not exceed the deployment ceiling",
        )
    return override.cost_ceiling


def _resolve_max_total_ready(deployment: WarmPoolRuntimePolicy, override: WarmPoolOverride) -> int:
    """Return the effective max-total-ready cap; the override may only lower it."""
    if override.max_total_ready is None:
        return deployment.max_total_ready
    baseline = deployment.max_total_ready or override.max_total_ready
    return _narrow_int(baseline, override.max_total_ready, "max_total_ready")


def resolve_effective_policy(
    deployment: WarmPoolRuntimePolicy, override: WarmPoolOverride | None = None
) -> WarmPoolRuntimePolicy:
    """Resolve the effective policy from a deployment policy and a narrowing override.

    Pure and server-side. An override may only narrow; any attempt to widen a limit,
    name an unknown bucket, or add a bucket raises :class:`WarmPoolPolicyError`.
    """
    if override is None or _override_is_noop(override):
        return deployment
    if override.disable:
        return cast(WarmPoolRuntimePolicy, replace(deployment, enabled=False, buckets=()))

    deployment_ids = {b.id for b in deployment.buckets}
    return cast(
        WarmPoolRuntimePolicy,
        replace(
            deployment,
            max_total_ready=_resolve_max_total_ready(deployment, override),
            replenish_concurrency=_narrow_int(
                deployment.replenish_concurrency, override.replenish_concurrency, "replenish_concurrency"
            ),
            cost_ceiling=_resolve_cost_ceiling(deployment, override),
            buckets=_select_narrowed_buckets(deployment, override, deployment_ids),
        ),
    )
