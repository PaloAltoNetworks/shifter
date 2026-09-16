"""Deployment-owned partition and metric catalog (PLAT-201).

The catalog is the allowlist. A partition exists because a deployment declared
it, and a metric is assessed because the catalog says how to measure it -- never
because an event name, a scenario, an organizer hint, or a mutable global
setting implied one.

Parsing is deliberately strict and fails loud at the composition root rather
than defaulting. A misspelled ``enforcment`` key that silently left a metric
advisory, or an out-of-range safety margin that silently clamped, would change
admission behaviour with no signal; a deployment that cannot express its
intended policy should refuse to boot instead.

Stdlib-only, matching the rest of ``shared.capacity``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256

from shared.capacity.contract import (
    CapacityMetricSpec,
    EnforcementMode,
    MeasurementSource,
    PartitionRef,
    ProviderMetricRef,
)

_PARTITION_REQUIRED = ("name", "provider", "account", "region", "backend")
_PARTITION_OPTIONAL = ("policy_profile",)
_METRIC_REQUIRED = ("name", "dimension", "unit", "partition", "source", "freshness_seconds")
_METRIC_OPTIONAL = (
    "safety_margin_ratio",
    "enforcement",
    "provider_ref",
    "per_range_cost",
    "per_node_cost",
)
_PROVIDER_REF_REQUIRED = ("limit_ref",)
_PROVIDER_REF_OPTIONAL = ("usage_ref",)


class CapacityCatalogError(ValueError):
    """Raised when the declared capacity catalog is malformed.

    Deployment configuration, not user input: the correct response is to fail
    closed at startup so the deployment is fixed, never to fall back to a
    partial catalog that admits events against metrics nobody meant to declare.
    """


@dataclass(frozen=True)
class CapacityCatalog:
    """Parsed, validated capacity policy for one deployment."""

    partitions: dict[str, PartitionRef] = field(default_factory=dict)
    policy_version: str = ""
    _metrics: dict[str, tuple[CapacityMetricSpec, ...]] = field(default_factory=dict)

    def metrics_for(self, partition_name: str) -> tuple[CapacityMetricSpec, ...]:
        """Return the metrics declared for ``partition_name`` (empty when unknown)."""
        return self._metrics.get(partition_name, ())


def load_catalog(payload: Mapping[str, object]) -> CapacityCatalog:
    """Parse and validate a capacity catalog payload.

    Raises :class:`CapacityCatalogError` on any structural problem: unknown
    keys, missing required fields, out-of-range numbers, unknown enum values,
    duplicate names, or a metric pointing at a partition that was not declared.
    """
    if not isinstance(payload, Mapping):
        raise CapacityCatalogError("capacity catalog must be a mapping")

    _reject_unknown_keys(payload, ("partitions", "metrics"), "catalog")

    partitions = _parse_partitions(payload.get("partitions", ()))
    metrics = _parse_metrics(payload.get("metrics", ()), partitions)

    return CapacityCatalog(
        partitions=partitions,
        policy_version=_fingerprint(partitions, metrics),
        _metrics=metrics,
    )


def load_catalog_json(raw: str) -> CapacityCatalog:
    """Parse a catalog from its JSON deployment representation."""
    text = (raw or "").strip()
    if not text:
        return CapacityCatalog(policy_version=_fingerprint({}, {}))
    try:
        decoded = json.loads(text)
    except ValueError as exc:
        raise CapacityCatalogError(f"capacity catalog is not valid JSON: {exc}") from exc
    return load_catalog(decoded)


def _reject_unknown_keys(mapping: Mapping[str, object], allowed: Sequence[str], what: str) -> None:
    """Fail when ``mapping`` carries a key outside ``allowed``."""
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise CapacityCatalogError(f"unknown {what} key(s): {', '.join(unknown)}")


def _require_str(mapping: Mapping[str, object], key: str, what: str) -> str:
    """Return a required non-empty string field."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CapacityCatalogError(f"{what} field '{key}' must be a non-empty string")
    return value.strip()


def _parse_partitions(raw: object) -> dict[str, PartitionRef]:
    """Parse the declared partition allowlist."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise CapacityCatalogError("catalog 'partitions' must be a list")

    partitions: dict[str, PartitionRef] = {}
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise CapacityCatalogError("each partition must be a mapping")
        _reject_unknown_keys(entry, (*_PARTITION_REQUIRED, *_PARTITION_OPTIONAL), "partition")
        for required in _PARTITION_REQUIRED:
            _require_str(entry, required, "partition")

        name = _require_str(entry, "name", "partition")
        if name in partitions:
            raise CapacityCatalogError(f"duplicate partition name: {name}")

        profile = entry.get("policy_profile", "default")
        if not isinstance(profile, str) or not profile.strip():
            raise CapacityCatalogError("partition field 'policy_profile' must be a non-empty string")

        partitions[name] = PartitionRef(
            name=name,
            provider=_require_str(entry, "provider", "partition"),
            account=_require_str(entry, "account", "partition"),
            region=_require_str(entry, "region", "partition"),
            backend=_require_str(entry, "backend", "partition"),
            policy_profile=profile.strip(),
        )
    return partitions


def _parse_metrics(
    raw: object,
    partitions: Mapping[str, PartitionRef],
) -> dict[str, tuple[CapacityMetricSpec, ...]]:
    """Parse metric catalog entries, binding each to a declared partition."""
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise CapacityCatalogError("catalog 'metrics' must be a list")

    by_partition: dict[str, list[CapacityMetricSpec]] = {}
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise CapacityCatalogError("each metric must be a mapping")
        _reject_unknown_keys(entry, (*_METRIC_REQUIRED, *_METRIC_OPTIONAL), "metric")

        partition_name = _require_str(entry, "partition", "metric")
        if partition_name not in partitions:
            raise CapacityCatalogError(f"metric targets undeclared partition: {partition_name}")

        spec = CapacityMetricSpec(
            name=_require_str(entry, "name", "metric"),
            dimension=_require_str(entry, "dimension", "metric"),
            unit=_require_str(entry, "unit", "metric"),
            partition=partition_name,
            source=_parse_enum(entry.get("source"), MeasurementSource, "source"),
            freshness_seconds=_parse_positive_int(entry.get("freshness_seconds")),
            safety_margin_ratio=_parse_ratio(entry.get("safety_margin_ratio", 0.0)),
            enforcement=_parse_enum(entry.get("enforcement", EnforcementMode.ADVISORY), EnforcementMode, "enforcement"),
            provider_ref=_parse_provider_ref(entry.get("provider_ref")),
            per_range_cost=_parse_cost(entry.get("per_range_cost", 0.0), "per_range_cost"),
            per_node_cost=_parse_cost(entry.get("per_node_cost", 0.0), "per_node_cost"),
        )

        declared = by_partition.setdefault(partition_name, [])
        if any(existing.name == spec.name for existing in declared):
            raise CapacityCatalogError(f"duplicate metric '{spec.name}' in partition '{partition_name}'")
        declared.append(spec)

    return {name: tuple(specs) for name, specs in by_partition.items()}


def _parse_enum[EnumT: StrEnum](value: object, enum_cls: type[EnumT], what: str) -> EnumT:
    """Coerce ``value`` into ``enum_cls``, rejecting anything outside it."""
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        allowed = ", ".join(sorted(member.value for member in enum_cls))
        raise CapacityCatalogError(f"metric field '{what}' must be one of: {allowed}") from exc


def _parse_positive_int(value: object) -> int:
    """Return a strictly positive integer, rejecting zero, negatives, and non-ints."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapacityCatalogError("metric field 'freshness_seconds' must be a positive integer")
    if value <= 0:
        raise CapacityCatalogError("metric field 'freshness_seconds' must be greater than zero")
    return value


def _parse_ratio(value: object) -> float:
    """Return a safety-margin ratio in [0, 1).

    One or more would reserve the entire limit, making every assessment fail
    regardless of real headroom, so it is a configuration error rather than a
    clamped value.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CapacityCatalogError("metric field 'safety_margin_ratio' must be a number")
    ratio = float(value)
    if not (0.0 <= ratio < 1.0):
        raise CapacityCatalogError("metric field 'safety_margin_ratio' must be >= 0 and < 1")
    return ratio


def _parse_cost(value: object, what: str) -> float:
    """Return a non-negative cost coefficient.

    A negative cost would subtract from demand and could admit an event that
    does not fit, so it is a configuration error rather than a clamped value.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CapacityCatalogError(f"metric field '{what}' must be a number")
    cost = float(value)
    if cost < 0:
        raise CapacityCatalogError(f"metric field '{what}' must be >= 0")
    return cost


def _parse_provider_ref(value: object) -> ProviderMetricRef | None:
    """Parse optional provider coordinates for a metric."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CapacityCatalogError("metric field 'provider_ref' must be a mapping")
    _reject_unknown_keys(value, (*_PROVIDER_REF_REQUIRED, *_PROVIDER_REF_OPTIONAL), "provider_ref")
    usage_ref = value.get("usage_ref", "")
    if not isinstance(usage_ref, str):
        raise CapacityCatalogError("provider_ref field 'usage_ref' must be a string")
    return ProviderMetricRef(
        limit_ref=_require_str(value, "limit_ref", "provider_ref"),
        usage_ref=usage_ref.strip(),
    )


def _fingerprint(
    partitions: Mapping[str, PartitionRef],
    metrics: Mapping[str, tuple[CapacityMetricSpec, ...]],
) -> str:
    """Return a stable version identifier for the parsed catalog.

    Order-insensitive so a reordered deployment file does not read as a policy
    change, but sensitive to every value that affects an admission decision, so
    an assessment record can be tied to the policy that produced it.
    """
    normalized = {
        "partitions": sorted(
            [[p.name, p.provider, p.account, p.region, p.backend, p.policy_profile] for p in partitions.values()]
        ),
        "metrics": sorted(
            [
                [
                    spec.partition,
                    spec.name,
                    spec.dimension,
                    spec.unit,
                    str(spec.source),
                    str(spec.freshness_seconds),
                    f"{spec.safety_margin_ratio:.6f}",
                    str(spec.enforcement),
                    spec.provider_ref.limit_ref if spec.provider_ref else "",
                    spec.provider_ref.usage_ref if spec.provider_ref else "",
                    f"{spec.per_range_cost:.6f}",
                    f"{spec.per_node_cost:.6f}",
                ]
                for specs in metrics.values()
                for spec in specs
            ]
        ),
    }
    digest = sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()[:16]
