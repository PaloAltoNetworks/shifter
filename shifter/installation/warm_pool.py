"""Provider-neutral range warm-pool policy (#28).

The platform shall accept operator configuration for a warm pool of
pre-provisioned, system-owned range generations that an initial launch can
atomically claim, reducing cold-start latency without bypassing capacity,
tenancy, or lifecycle controls. This module owns the public *shape* and the
cross-backend validation of that policy; it is a shared, cross-backend platform
setting exactly like :mod:`installation.range_egress`, not a backend-owned key.

The policy is deliberately **disabled by default** (``enabled=False`` with no
buckets): omitting the block preserves the cold-provisioning baseline. It is a
closed contract (``extra='forbid'``) and rejects unsafe values rather than
normalizing them. It carries **no** provider credentials, account/project
overrides, command fragments, or arbitrary extension dictionaries — those would
cross the trust boundary the operation contract keeps closed (ADR-043).

A warm *bucket* is one compatibility class the pool maintains ready. Its
compatibility dimensions (backend, region, scenario/immutable revision, image
set, access mode) are the operator-declared narrowing of *which* launches a
generation can serve; the authoritative match at claim time is the canonical
compatibility digest computed from immutable launch inputs
(:mod:`shared.warm_pool.compatibility`). The bucket declaration names the
dimensions; it is never itself the compatibility proof.

The consumers of the validated policy are the warm-pool reconciler (which
provisions/retires generations toward each bucket's target) and the CMS launch
claim path (which matches a ready generation). Both receive the normalized,
non-secret runtime projection from :func:`runtime_projection`; policy JSON is
never sent to the provisioner or placed in argv (preflight #28).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import ConfigIssue

#: The reserved key under ``RootConfig.settings`` that carries the policy.
SETTINGS_KEY = "warm_pool"

# A bucket id / partition / metric identifier: lowercase letters/digits with internal
# hyphens, 1-40 chars. DNS-label-safe so it can label metrics and manifests.
_IDENTIFIER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
# A scenario id or immutable scenario revision the bucket warms. Broader than an
# identifier (scenario ids carry dots and underscores) but still bounded and
# free of whitespace / path separators.
_SCENARIO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# An access-mode / region token: bounded, no whitespace, provider-neutral vocabulary
# validated for *shape* here; the capability/catalog layer owns the closed set.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Deployment-owned ceilings. These are hard upper bounds on operator input so a
# typo cannot request an unbounded or absurd pool; they are not the runtime
# capacity ceiling (that is the catalog + Engine admission layer, ADR-047).
_MAX_READY_PER_BUCKET = 1024
_MAX_TOTAL_READY = 4096
_MAX_CONCURRENCY = 256
_MIN_REPLENISH_INTERVAL_S = 1
_MAX_REPLENISH_INTERVAL_S = 86_400
_MIN_IDLE_TTL_S = 1
_MAX_IDLE_TTL_S = 604_800  # 7 days
_MAX_IMAGE_SET = 64


def _validate_identifier(value: str) -> str:
    """Validate a DNS-label-safe identifier (bucket id / partition / metric)."""
    if not isinstance(value, str):
        raise ValueError("must be a string")
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(
            "must be 1-40 characters of lowercase letters, digits, and internal hyphens (a DNS-label-safe identifier)"
        )
    return value


def _validate_scenario(value: str) -> str:
    """Validate a scenario id or immutable scenario revision token."""
    if not isinstance(value, str) or not _SCENARIO_RE.match(value):
        raise ValueError("must be 1-128 characters of letters, digits, '.', '_', or '-' with no whitespace")
    return value


def _validate_token(value: str) -> str:
    """Validate a bounded region / access-mode token (shape only)."""
    if not isinstance(value, str) or not _TOKEN_RE.match(value):
        raise ValueError("must be 1-64 characters of letters, digits, '.', '_', or '-' with no whitespace")
    return value


Identifier = Annotated[str, AfterValidator(_validate_identifier)]
ScenarioToken = Annotated[str, AfterValidator(_validate_scenario)]
Token = Annotated[str, AfterValidator(_validate_token)]


class WarmPoolBackend(StrEnum):
    """The range backend a warm bucket targets.

    Warm activation is an *optional* per-backend capability (ADR-039-R11). Only
    ``gce`` is warm-activation-capable today; ``aws`` and ``gdc`` are accepted in
    the vocabulary (a deployment may declare a bucket for a backend that reports
    the capability as unsupported), but such a bucket safely never yields a claim
    because the launch path falls back to cold provisioning when the resolved
    backend does not advertise ``range-warm-activation/v1``. Keeping the
    vocabulary closed here fails an unknown backend at config load.
    """

    AWS = "aws"
    GCE = "gce"
    GDC = "gdc"


class WarmPoolScaleDownStrategy(StrEnum):
    """How the reconciler chooses which excess *unclaimed* generation to retire.

    Scale-down never removes a claimed generation and never retains an unsafe or
    expired entry merely to satisfy ``minimum`` (preflight #28).
    """

    OLDEST_FIRST = "oldest-first"
    NEWEST_FIRST = "newest-first"


class WarmPoolReplacementStrategy(StrEnum):
    """How the reconciler handles an unhealthy generation.

    ``destroy-and-replace`` retires the unhealthy generation through the canonical
    lifecycle and lets normal replenishment refill toward ``target``.
    ``destroy-only`` retires it without proactively replacing (the pool converges
    on the next replenishment pass when below ``minimum``).
    """

    DESTROY_AND_REPLACE = "destroy-and-replace"
    DESTROY_ONLY = "destroy-only"


class WarmPoolBucket(BaseModel):
    """One compatibility class the warm pool maintains ready.

    ``id`` is a stable, unique bucket identity used for metrics labels and ledger
    scoping. The compatibility dimensions declare *which* launches a generation in
    this bucket can serve; the authoritative claim-time match is the canonical
    compatibility digest, not these fields.
    """

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    backend: WarmPoolBackend
    scenario: ScenarioToken
    #: The declared capacity partition this bucket's generations draw from. Must
    #: name a partition the deployment capacity catalog declares (cross-checked at
    #: the Engine capacity boundary, ADR-047); shape-validated here.
    capacity_partition: Identifier
    target: int = 0
    minimum: int = 0
    maximum: int = 0
    #: Maximum warm-idle lifetime for a ready generation in this bucket, seconds.
    idle_ttl_seconds: int = 3600
    #: Optional narrowing compatibility dimensions. Empty means "any" for that
    #: dimension within the backend+scenario class; the digest still decides.
    region: Token | None = None
    access_mode: Token | None = None
    image_set: list[Token] = Field(default_factory=list)
    #: Optional per-bucket cost ceiling as a catalog-declared metric value. A
    #: null value defers to the deployment-level ceiling.
    cost_ceiling: float | None = None

    @model_validator(mode="after")
    def _check_bucket_invariants(self) -> WarmPoolBucket:
        if not 0 <= self.minimum <= self.target <= self.maximum:
            raise ValueError(
                f"bucket {self.id!r} requires 0 <= minimum <= target <= maximum "
                f"(got minimum={self.minimum}, target={self.target}, maximum={self.maximum})"
            )
        if self.maximum > _MAX_READY_PER_BUCKET:
            raise ValueError(f"bucket {self.id!r} maximum {self.maximum} exceeds the ceiling {_MAX_READY_PER_BUCKET}")
        if not _MIN_IDLE_TTL_S <= self.idle_ttl_seconds <= _MAX_IDLE_TTL_S:
            raise ValueError(
                f"bucket {self.id!r} idle_ttl_seconds {self.idle_ttl_seconds} must be between "
                f"{_MIN_IDLE_TTL_S} and {_MAX_IDLE_TTL_S}"
            )
        if len(self.image_set) > _MAX_IMAGE_SET:
            raise ValueError(f"bucket {self.id!r} image_set exceeds {_MAX_IMAGE_SET} entries")
        if len(set(self.image_set)) != len(self.image_set):
            raise ValueError(f"bucket {self.id!r} image_set has duplicate entries")
        if self.cost_ceiling is not None and self.cost_ceiling < 0:
            raise ValueError(f"bucket {self.id!r} cost_ceiling must be non-negative")
        return self


class WarmPoolPolicy(BaseModel):
    """Operator-declared warm-pool policy for initial range launches (#28).

    Provider-neutral. Disabled by default: an omitted block, or ``enabled=False``,
    preserves cold provisioning. When enabled the policy must declare at least one
    bucket. Deployment-level fields bound cadence, concurrency, total ready
    capacity, cost, and scale-down/replacement behavior across all buckets.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: Reconciliation cadence, seconds. Bounded positive.
    replenish_interval_seconds: int = 300
    #: Maximum concurrent warm provisions/retirements per reconcile pass.
    replenish_concurrency: int = 1
    #: Hard ceiling on total nonterminal unclaimed generations (ready +
    #: provisioning) across all buckets. ``0`` means "sum of bucket maxima".
    max_total_ready: int = 0
    #: Optional deployment cost ceiling as a catalog-declared metric value.
    cost_ceiling: float | None = None
    scale_down: WarmPoolScaleDownStrategy = WarmPoolScaleDownStrategy.OLDEST_FIRST
    replacement: WarmPoolReplacementStrategy = WarmPoolReplacementStrategy.DESTROY_AND_REPLACE
    buckets: list[WarmPoolBucket] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_policy_invariants(self) -> WarmPoolPolicy:
        if not self.enabled:
            # A disabled policy is the safe default; buckets are ignored but a
            # non-empty declaration under enabled=False is almost certainly an
            # operator error (they expected it to be running), so reject it.
            if self.buckets:
                raise ValueError(
                    "warm pool is disabled (enabled=false) but declares buckets; set enabled=true or remove buckets"
                )
            return self
        if not self.buckets:
            raise ValueError("warm pool is enabled but declares no buckets; add a bucket or set enabled=false")
        self._check_cadence_invariants()
        self._check_bucket_ceiling_invariants()
        if self.cost_ceiling is not None and self.cost_ceiling < 0:
            raise ValueError("cost_ceiling must be non-negative")
        return self

    def _check_cadence_invariants(self) -> None:
        """Validate the deployment cadence and concurrency bounds."""
        if not _MIN_REPLENISH_INTERVAL_S <= self.replenish_interval_seconds <= _MAX_REPLENISH_INTERVAL_S:
            raise ValueError(
                f"replenish_interval_seconds {self.replenish_interval_seconds} must be between "
                f"{_MIN_REPLENISH_INTERVAL_S} and {_MAX_REPLENISH_INTERVAL_S}"
            )
        if not 1 <= self.replenish_concurrency <= _MAX_CONCURRENCY:
            raise ValueError(
                f"replenish_concurrency {self.replenish_concurrency} must be between 1 and {_MAX_CONCURRENCY}"
            )

    def _check_bucket_ceiling_invariants(self) -> None:
        """Validate bucket id uniqueness and the total-ready ceiling accounting."""
        ids = [bucket.id for bucket in self.buckets]
        if len(set(ids)) != len(ids):
            dupes = sorted({bid for bid in ids if ids.count(bid) > 1})
            raise ValueError(f"duplicate bucket id(s): {dupes}")
        sum_maxima = sum(bucket.maximum for bucket in self.buckets)
        if self.max_total_ready and self.max_total_ready > _MAX_TOTAL_READY:
            raise ValueError(f"max_total_ready {self.max_total_ready} exceeds the ceiling {_MAX_TOTAL_READY}")
        effective_ceiling = self.max_total_ready or sum_maxima
        if effective_ceiling > _MAX_TOTAL_READY:
            raise ValueError(
                f"sum of bucket maxima {sum_maxima} exceeds the total-ready ceiling {_MAX_TOTAL_READY}; "
                "reduce bucket maxima or set an explicit max_total_ready"
            )
        if self.max_total_ready and self.max_total_ready < max((b.target for b in self.buckets), default=0):
            raise ValueError("max_total_ready is smaller than a single bucket target; it would starve that bucket")

    def is_active(self) -> bool:
        """Return True when the pool should be reconciled and claims attempted."""
        return self.enabled and bool(self.buckets)


def runtime_projection(policy: WarmPoolPolicy) -> dict[str, Any]:
    """Return the non-secret, validated runtime projection for portal/reconciler.

    This is the *only* shape rendered to the runtime. It carries no secrets,
    provider identity, or command material — just the validated policy the
    reconciler and claim path evaluate. ``build_operation_envelope`` and the
    provisioner never receive this; per-generation the Engine persists an exact
    effective-policy fingerprint instead (preflight #28).
    """
    return policy.model_dump(mode="json")


def validate_settings_block(settings: Mapping[str, Any]) -> tuple[dict[str, Any], list[ConfigIssue]]:
    """Validate the ``warm_pool`` block within a backend's ``settings`` mapping.

    Returns a ``(normalized_settings, issues)`` tuple mirroring
    :func:`installation.range_egress.validate_settings_block`:

    - ``normalized_settings`` is a shallow copy of the input with ``warm_pool``
      replaced by the normalized form (defaults applied, enums canonicalized).
      When the block is absent, the input is returned unchanged.
    - ``issues`` is a list of :class:`ConfigIssue` records anchored under
      ``settings.warm_pool``. Warm-pool policy is operator config, not secrets,
      so validation messages are surfaced verbatim.
    """
    normalized = dict(settings)
    raw = settings.get(SETTINGS_KEY)
    issues: list[ConfigIssue] = []
    if raw is not None and not isinstance(raw, Mapping):
        issues.append(
            ConfigIssue(
                f"settings.{SETTINGS_KEY}",
                f"must be a mapping describing the warm-pool policy; got {type(raw).__name__}",
            )
        )
    elif isinstance(raw, Mapping):
        try:
            policy = WarmPoolPolicy.model_validate(dict(raw))
            normalized[SETTINGS_KEY] = policy.model_dump(mode="json")
        except ValidationError as exc:
            issues = _issues_from_pydantic_error(exc)
    return normalized, issues


def _issues_from_pydantic_error(exc: ValidationError) -> list[ConfigIssue]:
    """Convert a ``WarmPoolPolicy`` validation error to ``settings.warm_pool.*`` issues."""
    issues: list[ConfigIssue] = []
    for err in exc.errors():
        loc_parts = [str(part) for part in err["loc"]]
        path = ".".join(["settings", SETTINGS_KEY, *loc_parts]) if loc_parts else f"settings.{SETTINGS_KEY}"
        issues.append(ConfigIssue(path, err["msg"]))
    return issues
