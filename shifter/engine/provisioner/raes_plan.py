"""Provisioner-side reader for the serialized RAES ProvisioningPlan (ADR-031, ADR-032).

The RAES-native provisioning path persists the *serialized RAES ProvisioningPlan*
in ``mission_control_range.range_config`` (see
``shifter_platform/shared/raes/runtime_target.py::serialize_provisioning_plan``).
The provisioner is a separate deployable and must not import the RAES producer
module family (ADR-024). It reads the persisted plan as plain data here.

Per ADR-032, Shifter does not re-model the plan into a Shifter-owned spec: this
module reads the RAES plan payloads via accessors that **mirror the reference
RAES backend** ``raes_backend_libvirt`` (``_payload.py`` / ``realization.py``) --
``os_family`` from ``payload.os_family`` then ``spec.node.os``; the image from
``spec.node.source`` (name verbatim); sizing from ``spec.node.resources.ram``
(bytes -> MiB) and ``.cpu``; network membership from ``spec.infrastructure``. A
platform-side contract test (``tests/shared/raes/test_plan_provisioner_parity.py``)
guards this module's extraction against Shifter-owned fixtures. The consumer
accepts only the exact pinned ``raes`` producer version (ADR-032-R7); upgrading
that version requires re-validating these fixtures rather than using a live
differential against the reference backend's private accessors.

Sizing/image are exposed as ``None`` when the author omitted them, so the backend
applies its own default (e.g. a GCE profile machine type) rather than a forced
constant. It self-discriminates on the plan ``kind`` so an ``raes-range`` command
run against any foreign ``range_config`` fails loudly. The frozen value objects
live in ``raes_plan_types`` and ACL parsing in ``raes_acl`` (Sonar file-size split);
they are re-exported here so callers keep importing from ``raes_plan``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, cast

import raes_plan_contract
import raes_plan_domain
import raes_plan_resources
from raes_acl import build_node_acls
from raes_composition import (
    RaesPlanAccount,
    RaesPlanContent,
    RaesPlanFeature,
    build_account,
    build_content,
    build_feature,
)
from raes_plan_addressing import network_ip_assignments as _network_ip_assignments
from raes_plan_resources import (
    ACCOUNT_RESOURCE_TYPE,
    CONTENT_RESOURCE_TYPE,
    FEATURE_RESOURCE_TYPE,
    NETWORK_RESOURCE_TYPE,
    NODE_RESOURCE_TYPE,
    SUPPORTED_RESOURCE_TYPES,
)
from raes_plan_types import (
    RaesPlan,
    RaesPlanAcl,
    RaesPlanDomain,
    RaesPlanError,
    RaesPlanImage,
    RaesPlanNetwork,
    RaesPlanNode,
    RaesPlanServicePort,
)
from raes_plan_values import (
    _identity_lookup,
    _image,
    _infrastructure_spec,
    _memory_mib,
    _network,
    _network_refs,
    _network_selection_open,
    _node_count,
    _node_spec,
    _os_family,
    _os_identity_term,
    _resource_name,
    _vcpus,
)
from raes_service import build_node_services

SUPPORTED_ACCOUNT_AUTH_METHODS = raes_plan_domain.SUPPORTED_ACCOUNT_AUTH_METHODS

__all__ = [
    "RAES_PROVISIONING_PLAN_CONTRACT_VERSION",
    "SUPPORTED_ACCOUNT_AUTH_METHODS",
    "SUPPORTED_CONTRACT_VERSIONS",
    "SUPPORTED_RAES_VERSION",
    "SUPPORTED_RESOURCE_TYPES",
    "RaesPlan",
    "RaesPlanAccount",
    "RaesPlanAcl",
    "RaesPlanContent",
    "RaesPlanDomain",
    "RaesPlanError",
    "RaesPlanFeature",
    "RaesPlanImage",
    "RaesPlanNetwork",
    "RaesPlanNode",
    "RaesPlanServicePort",
    "parse_plan",
]

#: Must equal ``shared.raes.runtime_target.RAES_PROVISIONING_PLAN_KIND``.
RAES_PROVISIONING_PLAN_KIND = "raes_provisioning_plan"

#: Serialized-plan transport contract version this consumer accepts (ADR-032-R7).
#: The provisioner image ships without ``shared`` and must not import RAES
#: (ADR-024), so this is a Shifter-owned literal kept in lockstep with the producer
#: stamp ``shared.raes.contracts.RAES_PROVISIONING_PLAN_CONTRACT_VERSION`` by a
#: platform-side parity test (mirroring the ``RAES_PROVISIONING_PLAN_KIND`` pattern).
#: A new transport envelope shape is a new ``-vN`` member of the supported set.
RAES_PROVISIONING_PLAN_CONTRACT_VERSION = "raes-provisioning-plan-v2"
SUPPORTED_CONTRACT_VERSIONS: frozenset[str] = frozenset({RAES_PROVISIONING_PLAN_CONTRACT_VERSION})

#: Exact ``raes`` producer release this consumer accepts. A different producer
#: release is a different reviewed contract and is rejected before realization.
SUPPORTED_RAES_VERSION = "3.5.0"


#: A strict dotted-numeric release: ``MAJOR[.MINOR[.PATCH...]]`` with no pre-release
#: or build suffix. Anything else (``2.0.0rc1``, ``1garbage``, ``not-a-version``)
#: fails closed rather than being silently truncated to a numeric prefix.
_RELEASE_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")


def _release_tuple(version: str) -> tuple[int, ...]:
    """Parse a strict dotted-numeric release into an int tuple (fail closed).

    Only a pure ``MAJOR[.MINOR[.PATCH...]]`` string is accepted; a pre-release or
    build suffix, trailing text, or any non-numeric component raises
    :class:`RaesPlanError` rather than being accepted as a truncated prefix.
    """
    if not _RELEASE_VERSION_RE.fullmatch(version):
        raise RaesPlanError(f"raes_version {version!r} is not a valid release version")
    return tuple(int(segment) for segment in version.split("."))


def _validate_versions(envelope: Mapping[str, Any]) -> str:
    """Validate the transport contract and ``raes`` producer versions (ADR-032-R7).

    Returns the validated ``raes_version``; raises :class:`RaesPlanError` on an
    unsupported/absent contract version or a missing, malformed, or different
    producer version, so version-skewed plans never reach realization.
    """
    contract_version = envelope.get("contract_version")
    # Type-check the JSON discriminator before set membership: an unhashable value
    # (list/dict from a malformed envelope) must fail closed as RaesPlanError, not
    # raise TypeError outside the parser contract.
    if not isinstance(contract_version, str) or contract_version not in SUPPORTED_CONTRACT_VERSIONS:
        raise RaesPlanError(
            f"unsupported contract_version {contract_version!r} (supported: {sorted(SUPPORTED_CONTRACT_VERSIONS)})"
        )
    version = envelope.get("raes_version")
    if not isinstance(version, str) or not version.strip():
        raise RaesPlanError("raes_version must be a non-empty string")
    version = version.strip()
    _release_tuple(version)
    if version != SUPPORTED_RAES_VERSION:
        raise RaesPlanError(f"unsupported raes_version {version!r} (supported: {SUPPORTED_RAES_VERSION!r})")
    return version


def _build_composition[CompositionValue: (RaesPlanContent, RaesPlanAccount, RaesPlanFeature)](
    builder: Callable[[Mapping[str, Any]], CompositionValue | None],
    resource_type: str,
    pairs: list[tuple[str, Mapping[str, Any]]],
    node_lookup: dict[str, str],
    ordering_dependencies: Mapping[str, tuple[str, ...]],
) -> tuple[CompositionValue, ...]:
    """Build every composition value object of one kind, failing closed (ADR-032-R7).

    A payload missing required fields (``build_*`` returns ``None``) is a malformed
    resource; a placement whose ``target_address`` does not resolve to a declared
    node is a dangling composition reference. Both abort before an ``RaesPlan`` is
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


def _build_composition_value[CompositionValue: (RaesPlanContent, RaesPlanAccount, RaesPlanFeature)](
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
        raise RaesPlanError(str(exc)) from None
    if value is None:
        raise RaesPlanError(f"malformed {resource_type} resource at {address}")
    if isinstance(value, RaesPlanAccount):
        value = cast(
            CompositionValue,
            replace(
                cast(RaesPlanAccount, value),
                address=address,
                ordering_dependencies=ordering_dependencies.get(address, ()),
            ),
        )
    elif isinstance(value, RaesPlanContent):
        # Stamp the compiled resource address so #1564 delivery bindings (which
        # the CMS side keys by this same serialized-plan resource address) join
        # by a stable identity rather than by target_address/path.
        value = cast(CompositionValue, replace(cast(RaesPlanContent, value), address=address))
    elif isinstance(value, RaesPlanFeature):
        value = cast(
            CompositionValue,
            replace(
                cast(RaesPlanFeature, value),
                address=address,
                ordering_dependencies=ordering_dependencies.get(address, ()),
            ),
        )
    if value.target_address not in node_lookup:
        raise RaesPlanError(f"{resource_type} resource at {address} targets unknown node {value.target_address!r}")
    return value


def parse_plan(range_config: dict[str, Any] | None, *, cleanup_only: bool = False) -> RaesPlan:
    """Parse a serialized RAES plan from a range_config dict, failing closed.

    Self-discriminates on ``kind`` so an ``raes-range`` command run against a
    cyberscript (or otherwise foreign) ``range_config`` raises rather than
    realizing an unintended topology. It then validates the transport contract and
    ``raes`` producer versions and every topology term (ADR-032-R7): unknown
    resource types, malformed payloads, duplicate identities/aliases, and dangling
    network references all raise before any ``RaesPlan`` is returned -- i.e. before
    the caller reaches ``apply_raes_range_cell`` / ``destroy_raes_range_cell`` and
    any cloud mutation.
    """
    envelope = _require_mapping(range_config, where="range_config")
    kind = envelope.get("kind")
    if kind != RAES_PROVISIONING_PLAN_KIND:
        raise RaesPlanError(f"kind must be {RAES_PROVISIONING_PLAN_KIND!r}, got {kind!r}")
    if not cleanup_only:
        _validate_versions(envelope)
    envelope = raes_plan_contract.prepare_envelope(envelope, cleanup_only=cleanup_only)
    raes_version = envelope["raes_version"]

    resources = _require_mapping(envelope.get("resources"), where="resources")
    collected = raes_plan_resources.collect_resources(resources)
    network_lookup = _identity_lookup(collected.network_pairs, NETWORK_RESOURCE_TYPE)
    node_lookup = _identity_lookup(collected.node_pairs, NODE_RESOURCE_TYPE)
    networks = tuple(_network(address, payload) for address, payload in sorted(collected.network_pairs))
    network_by_address = {network.address: network for network in networks}
    nodes = tuple(
        _node(
            address,
            payload,
            network_lookup,
            network_by_address,
            collected.ordering_dependencies.get(address, ()),
        )
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
        raes_plan_domain.validate_account_credentials(account)
    features = _build_composition(
        build_feature,
        FEATURE_RESOURCE_TYPE,
        collected.composition[FEATURE_RESOURCE_TYPE],
        node_lookup,
        collected.ordering_dependencies,
    )
    domains = raes_plan_domain.build_domains(nodes, accounts)

    return RaesPlan(
        raes_version=raes_version,
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
    network_by_address: Mapping[str, RaesPlanNetwork],
    ordering_dependencies: tuple[str, ...],
) -> RaesPlanNode:
    """Build an RaesPlanNode, resolving network membership and ACL endpoints.

    Fails closed (ADR-032-R7) on a network-membership ref or an ACL ``from_net`` /
    ``to_net`` endpoint that no declared network resolves, rather than silently
    dropping it (which would provision a wrong topology or an unintended ACL).
    """
    resolved = _resolved_networks(address, payload, network_lookup)
    count = _node_count(payload)
    assignments = _network_ip_assignments(
        address,
        payload,
        network_lookup,
        network_by_address,
        resolved,
        count,
    )
    acls = _validated_node_acls(address, payload, network_lookup)
    topology = raes_plan_domain.topology(payload)
    return RaesPlanNode(
        address=address,
        name=_resource_name(address, payload),
        os_family=_os_family(payload),
        os_distribution=_os_identity_term(payload, "os_distribution"),
        os_version=_os_identity_term(payload, "os_version"),
        count=count,
        network_addresses=resolved,
        network_ip_assignments=assignments,
        network_selection_open=_network_selection_open(payload),
        ram_mib=_memory_mib(payload),
        vcpus=_vcpus(payload),
        image=_image(payload),
        acls=acls,
        services=build_node_services(_node_spec(payload).get("services")),
        ordering_dependencies=ordering_dependencies,
        domain_id=raes_plan_domain.topology_text(topology, "domain_id") or None,
        domain_role=raes_plan_domain.topology_text(topology, "role") or None,
        controller_addresses=raes_plan_domain.topology_addresses(topology, "controller_addresses") if topology else (),
        domain_profile=raes_plan_domain.topology_text(topology, "profile") or None,
        domain_dns_name=raes_plan_domain.topology_text(topology, "dns_name") or None,
        domain_netbios_name=raes_plan_domain.topology_text(topology, "netbios_name") or None,
        authority_account_address=raes_plan_domain.topology_text(topology, "authority_account_address") or None,
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
            raise RaesPlanError(f"node {address} references unknown network {ref!r}")
        resolved.append(target)
    return tuple(dict.fromkeys(resolved))


def _validated_node_acls(
    address: str,
    payload: Mapping[str, Any],
    network_lookup: Mapping[str, str],
) -> tuple[RaesPlanAcl, ...]:
    """Build node ACLs, failing closed on dangling network endpoints."""
    acls = build_node_acls(_infrastructure_spec(payload).get("acls"))
    for acl in acls:
        for endpoint in (acl.from_net, acl.to_net):
            if endpoint is not None and endpoint not in network_lookup:
                raise RaesPlanError(f"node {address} ACL {acl.name!r} references unknown network {endpoint!r}")
    return acls


def _require_mapping(value: object, *, where: str) -> Mapping[str, Any]:
    """Return ``value`` as a mapping or raise RaesPlanError naming ``where``."""
    if not isinstance(value, Mapping):
        raise RaesPlanError(f"{where} must be an object, got {type(value).__name__}")
    return value


def _string(value: object, *, where: str) -> str:
    """Return ``value`` as a non-empty string or raise RaesPlanError naming ``where``."""
    if not isinstance(value, str) or not value.strip():
        raise RaesPlanError(f"{where} must be a non-empty string")
    return value
