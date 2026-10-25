"""Dependency-light identity and shape checks for immutable operation inputs."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_KEY_SEPARATOR = ":"
_NODE_RESOURCE_TYPE = "node"


@dataclass(frozen=True)
class RaesRangeIdentity:
    """Stable range naming and the original cloud-resource creation generation."""

    legacy_range_id: int
    resource_generation: str | None = None


class RaesOperationInputError(Exception):
    """The RAES operation input is not a valid, bounded projection."""


def image_lookup_key(*, source_name: str | None, os_family: str | None) -> str:
    """Return the registry lookup key for one plan node.

    The authored RAES ``source`` keys the lookup; a source-less node falls back
    to its ``os_family`` so the backend can supply a base OS image (ADR-032
    base-OS policy).

    This is the *single* rule. The Engine uses it to scope which registry rows
    it projects; the provisioner uses it to resolve each node against that
    projection. If the two derivations ever diverge, the Engine omits a key the
    provisioner later asks for and the image silently goes missing at
    realization -- so both sides call this, and neither re-derives it.
    """
    return (source_name or None) or (os_family or None) or ""


def candidate_key(provider: str, source_name: str) -> str:
    """Return the transport key for one ``(provider, source_name)`` candidate set."""
    return f"{provider}{_KEY_SEPARATOR}{source_name}"


def _require(condition: bool, message: str) -> None:
    """Raise ``RaesOperationInputError(message)`` unless ``condition`` is true."""
    if not condition:
        raise RaesOperationInputError(message)


def _require_mapping(value: object, field: str) -> dict[str, Any]:
    """Return ``value`` as a mapping, else fail closed."""
    if not isinstance(value, Mapping):
        raise RaesOperationInputError(f"{field} must be an object")
    return dict(value)


def _require_exact_keys(
    value: Mapping[str, Any], allowed: frozenset[str], field: str, *, optional: frozenset[str] = frozenset()
) -> None:
    """Fail closed unless ``value`` carries exactly ``allowed`` (minus any ``optional``).

    ``optional`` keys may be present or absent; every other allowed key is required.
    This is the rolling-deploy compatibility seam: an ``optional`` key a newer
    producer emits is accepted, and its absence in an older queued input is also
    accepted, so producer and consumer can deploy independently.
    """
    actual = frozenset(value)
    unexpected = sorted(actual - allowed)
    _require(not unexpected, f"{field} has unexpected field(s): {', '.join(unexpected)}")
    missing = sorted((allowed - optional) - actual)
    _require(not missing, f"{field} is missing field(s): {', '.join(missing)}")


def plan_image_lookup_keys(plan: object) -> tuple[str, ...]:
    """Return the distinct registry lookup keys a serialized plan references.

    Walks the serialized ``ProvisioningPlan`` resources, keeping node payloads
    only, and returns each node's :func:`image_lookup_key` in first-seen order
    with duplicates collapsed. Empty keys (a node with neither an authored
    source nor an ``os_family``) are dropped: they cannot select a registry row.
    """
    resources = _require_mapping(plan, "raes plan").get("resources")
    if resources is None:
        # A plan with no resources block yields no image lookups. Validating the
        # plan itself is the provisioner's fail-closed ``raes_plan.parse_plan``;
        # scoping the registry projection must not become a second plan parser.
        return ()
    if not isinstance(resources, Mapping):
        raise RaesOperationInputError("raes plan resources must be an object")

    keys: list[str] = []
    for address, resource in resources.items():
        entry = _require_mapping(resource, f"raes plan resource '{address}'")
        if entry.get("resource_type") != _NODE_RESOURCE_TYPE:
            continue
        payload = _require_mapping(entry.get("payload"), f"raes plan resource '{address}' payload")
        node_spec = _require_mapping(payload.get("spec"), f"raes plan resource '{address}' spec").get("node") or {}
        node = _require_mapping(node_spec, f"raes plan resource '{address}' node spec")
        # A serialized node ``source`` is a mapping whose NAME selects the image
        # row (a bare string is the name); scope keys to the source, not os_family.
        source = node.get("source")
        source_name = source.get("name") if isinstance(source, Mapping) else source
        key = image_lookup_key(
            source_name=_optional_str(source_name),
            os_family=_optional_str(payload.get("os_family")),
        )
        if key and key not in keys:
            keys.append(key)
    return tuple(keys)


def _optional_str(value: object) -> str | None:
    """Return a non-empty string, or None for absent/blank/non-string values."""
    if isinstance(value, str) and value.strip():
        return value
    return None
