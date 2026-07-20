"""Provisioner-side extraction of ACES node ACLs (ADR-031, ADR-032).

Split out of ``aces_plan`` (Sonar file-size, mirroring ``aces_composition``): the
fail-closed parser that turns a node's authored ``spec.infrastructure.acls`` into
:class:`~aces_plan_types.AcesPlanAcl` value objects, normalizing action/protocol/
direction to the reference-backend vocabulary. Pure stdlib (no ``aces_*``); any
invalid field raises :class:`~aces_plan_types.AcesPlanError` so a malformed ACL is
never silently widened into a broad allow.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aces_plan_types import AcesPlanAcl, AcesPlanError

__all__ = ["build_node_acls"]

#: ACL vocabulary, mirrored from aces_backend_libvirt.acls (the reference backend).
_ACL_ACTIONS = {"allow": "accept", "accept": "accept", "deny": "drop", "drop": "drop"}
_ACL_WILDCARD_PROTOCOLS = frozenset({"", "all", "any"})
_ACL_DIRECTIONS = frozenset({"in", "out", "inout"})


def _acl_str(value: object) -> str:
    """Return ``value`` if it is a string, else an empty string."""
    return value if isinstance(value, str) else ""


def _acl_action(raw: Mapping[str, Any]) -> str:
    """Normalize an ACL action to ``accept``/``drop`` (mirror the reference)."""
    token = _acl_str(raw.get("action")).lower()
    if not token:
        raise AcesPlanError("ACL missing 'action'")
    if token not in _ACL_ACTIONS:
        raise AcesPlanError(f"ACL unknown action {token!r}")
    return _ACL_ACTIONS[token]


def _acl_protocol(raw: Mapping[str, Any]) -> str:
    """Normalize an ACL protocol to ``tcp``/``udp``/``all`` (mirror the reference)."""
    token = _acl_str(raw.get("protocol")).lower()
    if token in {"tcp", "udp"}:
        return token
    if token in _ACL_WILDCARD_PROTOCOLS:
        return "all"
    raise AcesPlanError(f"ACL unknown protocol {token!r}")


def _acl_direction(raw: Mapping[str, Any]) -> str:
    """Return the ACL direction (``in``/``out``/``inout``); default ``inout``."""
    token = _acl_str(raw.get("direction")).lower()
    if not token:
        return "inout"
    if token not in _ACL_DIRECTIONS:
        raise AcesPlanError(f"ACL unknown direction {token!r}")
    return token


def _acl_ports(raw: Mapping[str, Any]) -> tuple[int, ...]:
    """Return the ACL's validated integer ports (1-65535), rejecting bools/invalid."""
    raw_ports = raw.get("ports", ())
    if not isinstance(raw_ports, list | tuple):
        raise AcesPlanError("ACL 'ports' is not a list")
    ports: list[int] = []
    for port in raw_ports:
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port <= 65535:
            raise AcesPlanError(f"ACL invalid port {port!r}")
        ports.append(port)
    return tuple(ports)


def _acl_ref(raw: Mapping[str, Any], key: str) -> str | None:
    """Return the raw endpoint network ref (``from_net``/``to_net``); None if omitted."""
    ref = _acl_str(raw.get(key)).strip()
    return ref or None


def _acl(raw: object, index: int) -> AcesPlanAcl:
    """Build one AcesPlanAcl, failing loud (fail-closed) on any invalid field."""
    if not isinstance(raw, Mapping):
        raise AcesPlanError(f"ACL #{index} is not an object")
    protocol = _acl_protocol(raw)
    ports = _acl_ports(raw)
    if ports and protocol == "all":
        raise AcesPlanError(f"ACL #{index} ports require protocol 'tcp' or 'udp'")
    return AcesPlanAcl(
        name=_acl_str(raw.get("name")).strip() or f"acl-{index}",
        action=_acl_action(raw),
        direction=_acl_direction(raw),
        protocol=protocol,
        ports=ports,
        from_net=_acl_ref(raw, "from_net"),
        to_net=_acl_ref(raw, "to_net"),
    )


def build_node_acls(raw_acls: object) -> tuple[AcesPlanAcl, ...]:
    """Build a node's authored ACLs from a raw ``spec.infrastructure.acls`` value.

    A non-list value yields no ACLs; each entry is parsed fail-closed by :func:`_acl`.
    """
    if not isinstance(raw_acls, list | tuple):
        return ()
    return tuple(_acl(raw, index) for index, raw in enumerate(raw_acls))
