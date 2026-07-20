"""Provisioner-side reader for the serialized ACES ProvisioningPlan (ADR-031, ADR-032).

The ACES-native provisioning path persists the *serialized ACES ProvisioningPlan*
in ``mission_control_range.range_config`` (see
``shifter_platform/shared/aces/runtime_target.py::serialize_provisioning_plan``).
The provisioner is a separate deployable whose image ships only ``cyberscript`` on
``PYTHONPATH`` (no ``shared``, no Pydantic) and must not import any ``aces_*`` SDL
package (ADR-024). So it reads the plan as plain data here.

Per ADR-032, Shifter does not re-model the plan into a Shifter-owned spec: this
module reads the ACES plan payloads via accessors that **mirror the reference
ACES backend** ``aces_backend_libvirt`` (``_payload.py`` / ``realization.py``) --
``os_family`` from ``payload.os_family`` then ``spec.node.os``; the image from
``spec.node.source`` (name verbatim); sizing from ``spec.node.resources.ram``
(bytes -> MiB) and ``.cpu``; network membership from ``spec.infrastructure``. A
platform-side contract test (``tests/shared/aces/test_plan_provisioner_parity.py``)
guards this module's extraction against Shifter-owned fixtures; upstream ACES
convention changes are bounded by the supported ``aces-sdl`` version window
(ADR-032-R7) and re-validated when it is raised, rather than by a live differential
against the reference backend's private accessors.

Sizing/image are exposed as ``None`` when the author omitted them, so the backend
applies its own default (e.g. a GCE profile machine type) rather than a forced
constant. It self-discriminates on the plan ``kind`` so an ``aces-range`` command
run against a cyberscript ``range_config`` fails loudly. The frozen value objects
live in ``aces_plan_types`` and ACL parsing in ``aces_acl`` (Sonar file-size split);
they are re-exported here so callers keep importing from ``aces_plan``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, cast

import aces_plan_domain
import aces_plan_resources
from aces_acl import build_node_acls
from aces_composition import (
    AcesPlanAccount,
    AcesPlanContent,
    AcesPlanFeature,
    build_account,
    build_content,
    build_feature,
)
from aces_plan_resources import (
    ACCOUNT_RESOURCE_TYPE,
    CONTENT_RESOURCE_TYPE,
    FEATURE_RESOURCE_TYPE,
    NETWORK_RESOURCE_TYPE,
    NODE_RESOURCE_TYPE,
    SUPPORTED_RESOURCE_TYPES,
)
from aces_plan_types import (
    AcesPlan,
    AcesPlanAcl,
    AcesPlanDomain,
    AcesPlanError,
    AcesPlanImage,
    AcesPlanNetwork,
    AcesPlanNode,
    AcesPlanServicePort,
)
from aces_service import build_node_services

SUPPORTED_ACCOUNT_AUTH_METHODS = aces_plan_domain.SUPPORTED_ACCOUNT_AUTH_METHODS

__all__ = [
    "ACES_PROVISIONING_PLAN_CONTRACT_VERSION",
    "MAXIMUM_ACES_SDL_VERSION_EXCLUSIVE",
    "MINIMUM_ACES_SDL_VERSION",
    "SUPPORTED_ACCOUNT_AUTH_METHODS",
    "SUPPORTED_CONTRACT_VERSIONS",
    "SUPPORTED_RESOURCE_TYPES",
    "AcesPlan",
    "AcesPlanAccount",
    "AcesPlanAcl",
    "AcesPlanContent",
    "AcesPlanDomain",
    "AcesPlanError",
    "AcesPlanFeature",
    "AcesPlanImage",
    "AcesPlanNetwork",
    "AcesPlanNode",
    "AcesPlanServicePort",
    "parse_plan",
]

#: Must equal ``shared.aces.runtime_target.ACES_PROVISIONING_PLAN_KIND``.
ACES_PROVISIONING_PLAN_KIND = "aces_provisioning_plan"

#: Serialized-plan transport contract version this consumer accepts (ADR-032-R7).
#: The provisioner image ships without ``shared`` and must not import ``aces_*``
#: (ADR-024), so this is a Shifter-owned literal kept in lockstep with the producer
#: stamp ``shared.aces.contracts.ACES_PROVISIONING_PLAN_CONTRACT_VERSION`` by a
#: platform-side parity test (mirroring the ``ACES_PROVISIONING_PLAN_KIND`` pattern).
#: A new transport envelope shape is a new ``-vN`` member of the supported set.
ACES_PROVISIONING_PLAN_CONTRACT_VERSION = "aces-provisioning-plan-v1"
SUPPORTED_CONTRACT_VERSIONS: frozenset[str] = frozenset({ACES_PROVISIONING_PLAN_CONTRACT_VERSION})

#: Supported ``aces-sdl`` producer series this consumer accepts, as a bounded
#: half-open range ``[MINIMUM, MAXIMUM_EXCLUSIVE)`` (ADR-032-R7 fail-closed: an
#: unknown future release is rejected, not assumed compatible). The 0.19.1 floor
#: remains readable for already-persisted plans during rolling deployment, while
#: the platform producer is pinned exactly to 0.23.0. A platform-side test asserts
#: that exact producer pin equals the installed version and lies in this window.
#: Adopting a new series requires raising this window and passing the ACES
#: conformance gate.
MINIMUM_ACES_SDL_VERSION = "0.19.1"
MAXIMUM_ACES_SDL_VERSION_EXCLUSIVE = "0.24.0"

_MIB = 1024 * 1024


def _mapping(value: object) -> Mapping[str, Any]:
    """Return ``value`` if it is a mapping, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def _spec(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the payload's ``spec`` mapping, or an empty mapping."""
    return _mapping(payload.get("spec"))


def _node_spec(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the payload's ``spec.node`` mapping, or an empty mapping."""
    return _mapping(_spec(payload).get("node"))


def _infrastructure_spec(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the payload's ``spec.infrastructure`` mapping, or an empty mapping."""
    return _mapping(_spec(payload).get("infrastructure"))


def _resource_name(address: str, payload: Mapping[str, Any]) -> str:
    """Return the authored resource name, falling back to the address leaf."""
    name = payload.get("name") or payload.get("node_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return address.rsplit(".", 1)[-1]


def _os_family(payload: Mapping[str, Any]) -> str:
    """Mirror aces_backend_libvirt._os_family: os_family, else spec.node.os."""
    family = payload.get("os_family")
    if isinstance(family, str) and family:
        return family
    node_os = _node_spec(payload).get("os")
    return node_os if isinstance(node_os, str) else ""


def _node_count(payload: Mapping[str, Any]) -> int:
    """Return the node instance count (>= 1); default 1 for missing/invalid values."""
    raw = payload.get("count")
    if isinstance(raw, bool):
        return 1
    if isinstance(raw, int) and raw >= 1:
        return raw
    return 1


def _memory_mib(payload: Mapping[str, Any]) -> int | None:
    """Authored RAM -> MiB (mirror aces_backend_libvirt._memory_mib); None if absent."""
    raw = _mapping(_node_spec(payload).get("resources")).get("ram")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        if raw >= _MIB:
            return max(128, int((raw + _MIB - 1) // _MIB))
        return max(128, int(raw))
    return None


def _vcpus(payload: Mapping[str, Any]) -> int | None:
    """Authored CPU -> vcpus (mirror aces_backend_libvirt._vcpus); None if absent."""
    raw = _mapping(_node_spec(payload).get("resources")).get("cpu")
    if isinstance(raw, int | float) and not isinstance(raw, bool) and raw > 0:
        return max(1, int(raw))
    return None


def _image(payload: Mapping[str, Any]) -> AcesPlanImage | None:
    """Authored image from spec.node.source (name verbatim, mirror _image_ref)."""
    source = _node_spec(payload).get("source")
    if isinstance(source, str) and source.strip():
        return AcesPlanImage(name=source.strip())
    if isinstance(source, Mapping):
        name = source.get("name")
        if isinstance(name, str) and name.strip():
            version = source.get("version")
            return AcesPlanImage(
                name=name.strip(),
                version=version.strip() if isinstance(version, str) and version.strip() else None,
            )
    return None


def _network_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the network handles a node references (``networks`` then ``links``)."""
    infra = _infrastructure_spec(payload)
    for field_name in ("networks", "links"):
        raw = infra.get(field_name)
        if isinstance(raw, list | tuple):
            return tuple(ref for ref in raw if isinstance(ref, str) and ref.strip())
    return ()


def _network(address: str, payload: Mapping[str, Any]) -> AcesPlanNetwork:
    """Build an AcesPlanNetwork from a network resource payload (cidr/gateway/internal)."""
    props = _mapping(_infrastructure_spec(payload).get("properties"))
    cidr = props.get("cidr")
    gateway = props.get("gateway")
    return AcesPlanNetwork(
        address=address,
        name=_resource_name(address, payload),
        cidr=cidr.strip() if isinstance(cidr, str) and cidr.strip() else None,
        gateway=gateway.strip() if isinstance(gateway, str) and gateway.strip() else None,
        internal=props.get("internal") is True,
    )


def _identity_lookup(resources: list[tuple[str, Mapping[str, Any]]], kind: str) -> dict[str, str]:
    """Map every handle a resource may be referenced by to its canonical address.

    Handles are the canonical address, the authored name, and the address leaf.
    Fails closed (ADR-032-R7) when two distinct resources of ``kind`` share a
    handle, since a reference to that handle would be ambiguous.
    """
    lookup: dict[str, str] = {}
    for address, payload in resources:
        name = _resource_name(address, payload)
        for key in (address, name, address.rsplit(".", 1)[-1]):
            if not key:
                continue
            existing = lookup.get(key)
            if existing is not None and existing != address:
                raise AcesPlanError(f"duplicate {kind} alias {key!r} maps to {existing!r} and {address!r}")
            lookup[key] = address
    return lookup


#: A strict dotted-numeric release: ``MAJOR[.MINOR[.PATCH...]]`` with no pre-release
#: or build suffix. Anything else (``0.19.1rc1``, ``1garbage``, ``not-a-version``)
#: fails closed rather than being silently truncated to a numeric prefix.
_RELEASE_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")


def _release_tuple(version: str) -> tuple[int, ...]:
    """Parse a strict dotted-numeric release into an int tuple (fail closed).

    Only a pure ``MAJOR[.MINOR[.PATCH...]]`` string is accepted; a pre-release or
    build suffix, trailing text, or any non-numeric component raises
    :class:`AcesPlanError` rather than being accepted as a truncated prefix.
    """
    if not _RELEASE_VERSION_RE.fullmatch(version):
        raise AcesPlanError(f"aces_sdl_version {version!r} is not a valid release version")
    return tuple(int(segment) for segment in version.split("."))


def _validate_versions(envelope: Mapping[str, Any]) -> str:
    """Validate the transport contract and ``aces-sdl`` producer versions (ADR-032-R7).

    Returns the validated ``aces_sdl_version``; raises :class:`AcesPlanError` on an
    unsupported/absent contract version, or a missing/malformed producer version or
    one outside the bounded supported ``aces-sdl`` series -- so a version-skewed or
    unknown-future plan never reaches realization.
    """
    contract_version = envelope.get("contract_version")
    # Type-check the JSON discriminator before set membership: an unhashable value
    # (list/dict from a malformed envelope) must fail closed as AcesPlanError, not
    # raise TypeError outside the parser contract.
    if not isinstance(contract_version, str) or contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        raise AcesPlanError(
            f"unsupported contract_version {contract_version!r} (supported: {sorted(SUPPORTED_CONTRACT_VERSIONS)})"
        )
    version = envelope.get("aces_sdl_version")
    if not isinstance(version, str) or not version.strip():
        raise AcesPlanError("aces_sdl_version must be a non-empty string")
    version = version.strip()
    parsed = _release_tuple(version)
    if not _release_tuple(MINIMUM_ACES_SDL_VERSION) <= parsed < _release_tuple(MAXIMUM_ACES_SDL_VERSION_EXCLUSIVE):
        raise AcesPlanError(
            f"aces_sdl_version {version!r} is outside the supported range "
            f"[{MINIMUM_ACES_SDL_VERSION}, {MAXIMUM_ACES_SDL_VERSION_EXCLUSIVE})"
        )
    return version


def _build_composition[CompositionValue: (AcesPlanContent, AcesPlanAccount, AcesPlanFeature)](
    builder: Callable[[Mapping[str, Any]], CompositionValue | None],
    resource_type: str,
    pairs: list[tuple[str, Mapping[str, Any]]],
    node_lookup: dict[str, str],
    ordering_dependencies: Mapping[str, tuple[str, ...]],
) -> tuple[CompositionValue, ...]:
    """Build every composition value object of one kind, failing closed (ADR-032-R7).

    A payload missing required fields (``build_*`` returns ``None``) is a malformed
    resource; a placement whose ``target_address`` does not resolve to a declared
    node is a dangling composition reference. Both abort before an ``AcesPlan`` is
    returned, so credential/content bootstrap can never bind to an absent node.
    """
    return tuple(
        _build_composition_value(
            builder,
            resource_type,
            address,
            payload,
            node_lookup,
            ordering_dependencies,
        )
        for address, payload in pairs
    )


def _build_composition_value[CompositionValue: (AcesPlanContent, AcesPlanAccount, AcesPlanFeature)](
    builder: Callable[[Mapping[str, Any]], CompositionValue | None],
    resource_type: str,
    address: str,
    payload: Mapping[str, Any],
    node_lookup: Mapping[str, str],
    ordering_dependencies: Mapping[str, tuple[str, ...]],
) -> CompositionValue:
    """Build and validate one composition resource."""
    try:
        value = builder(payload)
    except ValueError as exc:
        raise AcesPlanError(str(exc)) from None
    if value is None:
        raise AcesPlanError(f"malformed {resource_type} resource at {address}")
    if isinstance(value, AcesPlanAccount):
        value = cast(
            CompositionValue,
            replace(
                cast(AcesPlanAccount, value),
                address=address,
                ordering_dependencies=ordering_dependencies.get(address, ()),
            ),
        )
    elif isinstance(value, AcesPlanContent):
        # Stamp the compiled resource address so #1564 delivery bindings (which
        # the CMS side keys by this same serialized-plan resource address) join
        # by a stable identity rather than by target_address/path.
        value = cast(CompositionValue, replace(cast(AcesPlanContent, value), address=address))
    if value.target_address not in node_lookup:
        raise AcesPlanError(f"{resource_type} resource at {address} targets unknown node {value.target_address!r}")
    return value


def parse_plan(range_config: dict[str, Any] | None) -> AcesPlan:
    """Parse a serialized ACES plan from a range_config dict, failing closed.

    Self-discriminates on ``kind`` so an ``aces-range`` command run against a
    cyberscript (or otherwise foreign) ``range_config`` raises rather than
    realizing an unintended topology. It then validates the transport contract and
    ``aces-sdl`` producer versions and every topology term (ADR-032-R7): unknown
    resource types, malformed payloads, duplicate identities/aliases, and dangling
    network references all raise before any ``AcesPlan`` is returned -- i.e. before
    the caller reaches ``apply_aces_range_cell`` / ``destroy_aces_range_cell`` and
    any cloud mutation.
    """
    envelope = _require_mapping(range_config, where="range_config")
    kind = envelope.get("kind")
    if kind != ACES_PROVISIONING_PLAN_KIND:
        raise AcesPlanError(f"kind must be {ACES_PROVISIONING_PLAN_KIND!r}, got {kind!r}")
    aces_sdl_version = _validate_versions(envelope)

    resources = _require_mapping(envelope.get("resources"), where="resources")
    collected = aces_plan_resources.collect_resources(resources)
    network_lookup = _identity_lookup(collected.network_pairs, NETWORK_RESOURCE_TYPE)
    node_lookup = _identity_lookup(collected.node_pairs, NODE_RESOURCE_TYPE)
    networks = tuple(_network(address, payload) for address, payload in sorted(collected.network_pairs))
    nodes = tuple(
        _node(address, payload, network_lookup, collected.ordering_dependencies.get(address, ()))
        for address, payload in sorted(collected.node_pairs)
    )
    content = _build_composition(
        build_content,
        CONTENT_RESOURCE_TYPE,
        collected.composition[CONTENT_RESOURCE_TYPE],
        node_lookup,
        collected.ordering_dependencies,
    )
    accounts = _build_composition(
        build_account,
        ACCOUNT_RESOURCE_TYPE,
        collected.composition[ACCOUNT_RESOURCE_TYPE],
        node_lookup,
        collected.ordering_dependencies,
    )
    for account in accounts:
        aces_plan_domain.validate_account_credentials(account)
    features = _build_composition(
        build_feature,
        FEATURE_RESOURCE_TYPE,
        collected.composition[FEATURE_RESOURCE_TYPE],
        node_lookup,
        collected.ordering_dependencies,
    )
    domains = aces_plan_domain.build_domains(nodes, accounts)

    return AcesPlan(
        aces_sdl_version=aces_sdl_version,
        nodes=nodes,
        networks=networks,
        content=content,
        accounts=accounts,
        features=features,
        domains=domains,
    )


def _node(
    address: str,
    payload: Mapping[str, Any],
    network_lookup: dict[str, str],
    ordering_dependencies: tuple[str, ...],
) -> AcesPlanNode:
    """Build an AcesPlanNode, resolving network membership and ACL endpoints.

    Fails closed (ADR-032-R7) on a network-membership ref or an ACL ``from_net`` /
    ``to_net`` endpoint that no declared network resolves, rather than silently
    dropping it (which would provision a wrong topology or an unintended ACL).
    """
    resolved = _resolved_networks(address, payload, network_lookup)
    acls = _validated_node_acls(address, payload, network_lookup)
    topology = aces_plan_domain.topology(payload)
    return AcesPlanNode(
        address=address,
        name=_resource_name(address, payload),
        os_family=_os_family(payload),
        count=_node_count(payload),
        network_addresses=resolved,
        ram_mib=_memory_mib(payload),
        vcpus=_vcpus(payload),
        image=_image(payload),
        acls=acls,
        services=build_node_services(_node_spec(payload).get("services")),
        ordering_dependencies=ordering_dependencies,
        domain_id=aces_plan_domain.topology_text(topology, "domain_id") or None,
        domain_role=aces_plan_domain.topology_text(topology, "role") or None,
        controller_addresses=aces_plan_domain.topology_addresses(topology, "controller_addresses") if topology else (),
        domain_profile=aces_plan_domain.topology_text(topology, "profile") or None,
        domain_dns_name=aces_plan_domain.topology_text(topology, "dns_name") or None,
        domain_netbios_name=aces_plan_domain.topology_text(topology, "netbios_name") or None,
        authority_account_address=aces_plan_domain.topology_text(topology, "authority_account_address") or None,
    )


def _resolved_networks(
    address: str,
    payload: Mapping[str, Any],
    network_lookup: Mapping[str, str],
) -> tuple[str, ...]:
    """Resolve a node's network aliases, failing closed on dangling refs."""
    resolved: list[str] = []
    for ref in _network_refs(payload):
        target = network_lookup.get(ref)
        if target is None:
            raise AcesPlanError(f"node {address} references unknown network {ref!r}")
        resolved.append(target)
    return tuple(dict.fromkeys(resolved))


def _validated_node_acls(
    address: str,
    payload: Mapping[str, Any],
    network_lookup: Mapping[str, str],
) -> tuple[AcesPlanAcl, ...]:
    """Build node ACLs, failing closed on dangling network endpoints."""
    acls = build_node_acls(_infrastructure_spec(payload).get("acls"))
    for acl in acls:
        for endpoint in (acl.from_net, acl.to_net):
            if endpoint is not None and endpoint not in network_lookup:
                raise AcesPlanError(f"node {address} ACL {acl.name!r} references unknown network {endpoint!r}")
    return acls


def _require_mapping(value: object, *, where: str) -> Mapping[str, Any]:
    """Return ``value`` as a mapping or raise AcesPlanError naming ``where``."""
    if not isinstance(value, Mapping):
        raise AcesPlanError(f"{where} must be an object, got {type(value).__name__}")
    return value


def _string(value: object, *, where: str) -> str:
    """Return ``value`` as a non-empty string or raise AcesPlanError naming ``where``."""
    if not isinstance(value, str) or not value.strip():
        raise AcesPlanError(f"{where} must be a non-empty string")
    return value
