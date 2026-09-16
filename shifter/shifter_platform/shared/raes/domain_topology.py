"""Sanitized RAES identity-domain topology admission (#1606).

RAES owns topology validation. Shifter preserves the public diagnostic identity
while replacing value-bearing messages before they can enter operational output.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from raes_backend_protocols.capabilities import ProvisionerCapabilities
from raes_backend_protocols.domain_topology import domain_topology_plan_diagnostics
from raes_contracts.diagnostics import Diagnostic, Severity
from raes_contracts.planning import ProvisioningPlan
from raes_contracts.runtime_state import RuntimeSnapshot

_MESSAGE = "authored identity-domain topology is invalid or unsupported by this backend"
_BACKEND_POLICY_MESSAGE = "authored identity-domain term is unsupported by this backend realization profile"
_DOMAIN_ACCOUNT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]{0,19}$")
_SPN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")


def _mapping(value: object) -> Mapping[str, Any]:
    """Return mapping values and normalize every other shape to empty."""
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    """Return string values and normalize every other shape to empty."""
    return value if isinstance(value, str) else ""


def _diagnostic(code: str, address: str) -> Diagnostic:
    """Build one sanitized backend-effect diagnostic."""
    return Diagnostic(
        code=code,
        domain="provisioning",
        address=address,
        message=_BACKEND_POLICY_MESSAGE,
        severity=Severity.ERROR,
    )


def _policy_resources(plan: ProvisioningPlan, snapshot: RuntimeSnapshot | None) -> dict[str, object]:
    """Return the current materializing resource view for backend-effect policy."""
    resources: dict[str, object] = {}
    if snapshot is not None:
        resources.update(snapshot.entries)
    resources.update(plan.resources)
    for operation in plan.operations:
        action = getattr(operation.action, "value", operation.action)
        if action == "delete":
            resources.pop(operation.address, None)
        else:
            resources[operation.address] = operation
    return resources


def _network_refs(payload: Mapping[str, Any]) -> frozenset[str]:
    """Return authored network addresses from either supported payload field."""
    infrastructure = _mapping(_mapping(payload.get("spec")).get("infrastructure"))
    for field in ("networks", "links"):
        raw = infrastructure.get(field)
        if isinstance(raw, list | tuple):
            return frozenset(item for item in raw if isinstance(item, str) and item)
    return frozenset()


def _node_os(payload: Mapping[str, Any]) -> str:
    """Return the normalized node operating-system family."""
    direct = _text(payload.get("os_family"))
    if direct:
        return direct.lower()
    return _text(_mapping(_mapping(payload.get("spec")).get("node")).get("os")).lower()


def _node_count(payload: Mapping[str, Any]) -> int:
    """Return a positive node count, defaulting malformed or omitted values to one."""
    value = payload.get("count")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 1


def _unsupported_domain_account(spec: Mapping[str, Any]) -> bool:
    """Return whether a domain account requests any unsupported effect."""
    unsupported_fields = (
        spec.get("groups"),
        _text(spec.get("shell")),
        _text(spec.get("home")),
        _text(spec.get("mail")),
        spec.get("disabled") is True,
    )
    identity_supported = _DOMAIN_ACCOUNT_NAME.fullmatch(_text(spec.get("username"))) is not None
    credential_supported = _text(spec.get("auth_method") or "password") == "password" and _text(
        spec.get("password_strength") or "medium"
    ) in {"weak", "medium", "strong"}
    return not identity_supported or not credential_supported or any(unsupported_fields)


def _invalid_spn(spn: str) -> bool:
    """Return whether an authored SPN is not a canonical bounded single line."""
    return _SPN.fullmatch(spn) is None or spn.strip() != spn or "\n" in spn or "\r" in spn


def _account_policy_diagnostics(address: str, payload: Mapping[str, Any]) -> list[Diagnostic]:
    """Validate the bounded account effects implemented by the AD realizer."""
    spec = _mapping(payload.get("spec"))
    domain_ref = _text(spec.get("domain_ref"))
    spn = _text(spec.get("spn"))
    diagnostics: list[Diagnostic] = []
    if spn and not domain_ref:
        diagnostics.append(_diagnostic("shifter-provisioner.account-spn-domain-required", address))
        return diagnostics
    if not domain_ref:
        return diagnostics

    if _unsupported_domain_account(spec):
        diagnostics.append(_diagnostic("shifter-provisioner.domain-account-policy-unsupported", address))
    if spn and _invalid_spn(spn):
        diagnostics.append(_diagnostic("shifter-provisioner.account-spn-invalid", address))
    return diagnostics


def _collect_policy_view(
    resources: Mapping[str, object],
) -> tuple[
    dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
    dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
    dict[str, dict[str, list[str]]],
    list[Diagnostic],
]:
    """Collect domain nodes, accounts, roles, and standalone account diagnostics."""
    nodes: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    accounts: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    domains: dict[str, dict[str, list[str]]] = {}
    diagnostics: list[Diagnostic] = []
    for address, resource in resources.items():
        payload = _mapping(getattr(resource, "payload", None))
        topology = _mapping(payload.get("domain_topology"))
        resource_type = _text(getattr(resource, "resource_type", ""))
        if resource_type == "account-placement":
            accounts[address] = (payload, topology)
            if not topology:
                diagnostics.extend(_account_policy_diagnostics(address, payload))
        if topology and resource_type == "node":
            nodes[address] = (payload, topology)
            domain_id = _text(topology.get("domain_id"))
            role = _text(topology.get("role"))
            domains.setdefault(domain_id, {"controller": [], "member": []}).setdefault(role, []).append(address)
    return nodes, accounts, domains, diagnostics


def _authority_diagnostics(
    controller_address: str,
    controller_topology: Mapping[str, Any],
    accounts: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> list[Diagnostic]:
    """Validate the exact bounded RID-500 authority account shape."""
    authority_address = _text(controller_topology.get("authority_account_address"))
    authority = accounts.get(authority_address)
    if authority is None:
        return [_diagnostic("shifter-provisioner.domain-authority-unsupported", controller_address)]
    authority_payload, _authority_topology = authority
    authority_spec = _mapping(authority_payload.get("spec"))
    unsupported_fields = any(
        (
            authority_spec.get("groups"),
            _text(authority_spec.get("shell")),
            _text(authority_spec.get("home")),
            _text(authority_spec.get("mail")),
            _text(authority_spec.get("spn")),
            _text(authority_spec.get("domain_ref")),
        )
    )
    valid = (
        _text(authority_spec.get("username")).casefold() == "administrator"
        and _text(authority_spec.get("auth_method") or "password") == "password"
        and _text(authority_spec.get("password_strength") or "medium") in {"weak", "medium", "strong"}
        and authority_spec.get("disabled") is not True
        and _text(authority_payload.get("target_address")) == controller_address
        and not unsupported_fields
    )
    return [] if valid else [_diagnostic("shifter-provisioner.domain-authority-unsupported", authority_address)]


def _member_diagnostics(
    member_addresses: list[str],
    nodes: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
    controller_networks: frozenset[str],
) -> list[Diagnostic]:
    """Validate member operating systems and controller reachability."""
    diagnostics: list[Diagnostic] = []
    for member_address in member_addresses:
        member_payload, _member_topology = nodes[member_address]
        if _node_os(member_payload) != "windows":
            diagnostics.append(_diagnostic("shifter-provisioner.domain-member-os-unsupported", member_address))
        member_networks = _network_refs(member_payload)
        if controller_networks and member_networks and controller_networks.isdisjoint(member_networks):
            diagnostics.append(_diagnostic("shifter-provisioner.domain-member-unreachable", member_address))
    return diagnostics


def _domain_account_diagnostics(
    domain_id: str,
    accounts: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
    authority_address: str,
) -> list[Diagnostic]:
    """Validate domain account bindings and case-insensitive uniqueness."""
    diagnostics: list[Diagnostic] = []
    seen_spns: set[str] = set()
    seen_users: set[str] = set()
    authority = accounts.get(authority_address)
    if authority is not None:
        seen_users.add(_text(_mapping(authority[0].get("spec")).get("username")).casefold())
    for account_address, (account_payload, account_topology) in accounts.items():
        spec = _mapping(account_payload.get("spec"))
        if _text(spec.get("domain_ref")) != domain_id:
            continue
        diagnostics.extend(_account_policy_diagnostics(account_address, account_payload))
        username_key = _text(spec.get("username")).casefold()
        spn_key = _text(spec.get("spn")).casefold()
        if username_key in seen_users:
            diagnostics.append(_diagnostic("shifter-provisioner.domain-account-duplicate", account_address))
        seen_users.add(username_key)
        if spn_key in seen_spns:
            diagnostics.append(_diagnostic("shifter-provisioner.account-spn-duplicate", account_address))
        if spn_key:
            seen_spns.add(spn_key)
        if _text(account_topology.get("domain_id")) != domain_id:
            diagnostics.append(_diagnostic("shifter-provisioner.domain-account-binding-invalid", account_address))
    return diagnostics


def backend_effect_domain_topology_diagnostics(
    plan: ProvisioningPlan,
    snapshot: RuntimeSnapshot | None = None,
) -> list[Diagnostic]:
    """Validate Shifter's bounded first Active Directory realization profile.

    RAES owns public topology semantics. This is only the narrower effect policy
    the current GCE/Windows implementation can genuinely realize.
    """
    nodes, accounts, domains, diagnostics = _collect_policy_view(_policy_resources(plan, snapshot))

    for domain_id, roles in domains.items():
        controllers = roles.get("controller", [])
        if len(controllers) != 1:
            diagnostics.append(_diagnostic("shifter-provisioner.domain-controller-cardinality-unsupported", "plan"))
            continue
        controller_address = controllers[0]
        controller_payload, controller_topology = nodes[controller_address]
        if _node_os(controller_payload) != "windows" or _node_count(controller_payload) != 1:
            diagnostics.append(
                _diagnostic("shifter-provisioner.domain-controller-cardinality-unsupported", controller_address)
            )
        diagnostics.extend(_authority_diagnostics(controller_address, controller_topology, accounts))
        diagnostics.extend(_member_diagnostics(roles.get("member", []), nodes, _network_refs(controller_payload)))
        diagnostics.extend(
            _domain_account_diagnostics(
                domain_id,
                accounts,
                _text(controller_topology.get("authority_account_address")),
            )
        )

    return diagnostics


def sanitized_domain_topology_diagnostics(
    plan: ProvisioningPlan,
    capabilities: ProvisionerCapabilities,
    snapshot: RuntimeSnapshot | None = None,
) -> list[Diagnostic]:
    """Return public topology diagnostics with value-free Shifter messages."""
    return [
        Diagnostic(
            code=diagnostic.code,
            domain="provisioning",
            address=diagnostic.address or "plan",
            message=_MESSAGE,
            severity=Severity.ERROR,
        )
        for diagnostic in domain_topology_plan_diagnostics(
            plan,
            snapshot=snapshot,
            supported_domain_profiles=capabilities.supported_domain_profiles,
        )
    ]
