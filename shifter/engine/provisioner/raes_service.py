"""Provisioner-side extraction of RAES node service ports (ADR-031, ADR-032, ADR-032-R8).

Split out of ``raes_plan`` (Sonar file-size, mirroring ``raes_acl``): the fail-closed
parser that turns a node's authored ``spec.node.services`` into
:class:`~raes_plan_types.RaesPlanServicePort` value objects, normalizing the protocol
to the reference-backend vocabulary (``tcp``/``udp``). Pure stdlib (no ``raes_*``); any
invalid field raises :class:`~raes_plan_types.RaesPlanError` so a malformed service is
never silently dropped, an unknown protocol is never coerced to TCP, and a declared
service is never widened into an unintended ingress rule (ADR-032-R8). Unlike ``acls``,
a *present* but non-sequence ``services`` value fails closed rather than being ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from raes_plan_types import RaesPlanError, RaesPlanServicePort

__all__ = ["build_node_services"]

#: Supported transport protocols, mirroring the reference backend's L4 vocabulary.
_SERVICE_PROTOCOLS = frozenset({"tcp", "udp"})
#: Authored ``ServicePort.protocol`` defaults to TCP when omitted/blank (raes).
_DEFAULT_PROTOCOL = "tcp"
#: Upper bound on an accepted service name at this trust boundary. The name is never
#: provider identity; the bound stops an unbounded authored string from flowing into
#: the plan/diagnostics. Comfortably above any real OCSF NetworkEndpoint name.
_MAX_SERVICE_NAME_LEN = 64

# Diagnostics name the service index and field only -- never the raw authored value
# (ADR-032-R8: bounded structural messages). The provisioner ships without ``shared``
# so ``safe_log_value`` is unavailable; field-only phrasing is the fail-closed answer.


def _service_port(raw: Mapping[str, Any], index: int) -> int:
    """Return a concrete integer port (1-65535); reject bool/float/str/out-of-range."""
    port = raw.get("port")
    # bool is an int subclass; reject it explicitly so ``True`` is never port 1.
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port <= 65535:
        raise RaesPlanError(f"service #{index} port must be an integer in 1-65535")
    return port


def _service_protocol(raw: Mapping[str, Any], index: int) -> str:
    """Normalize the service protocol to ``tcp``/``udp`` (TCP default; unknown raises)."""
    proto = raw.get("protocol")
    if proto is None or proto == "":
        return _DEFAULT_PROTOCOL
    if not isinstance(proto, str) or proto.lower() not in _SERVICE_PROTOCOLS:
        raise RaesPlanError(f"service #{index} protocol must be tcp or udp")
    return proto.lower()


def _service_name(raw: Mapping[str, Any], index: int) -> str:
    """Return the optional service name as a bounded string (never provider identity)."""
    name = raw.get("name")
    if name is None:
        return ""
    if not isinstance(name, str):
        raise RaesPlanError(f"service #{index} name must be a string")
    stripped = name.strip()
    if len(stripped) > _MAX_SERVICE_NAME_LEN:
        raise RaesPlanError(f"service #{index} name exceeds {_MAX_SERVICE_NAME_LEN} characters")
    return stripped


def _service(raw: object, index: int) -> RaesPlanServicePort:
    """Build one RaesPlanServicePort, failing loud (fail-closed) on any invalid field."""
    if not isinstance(raw, Mapping):
        raise RaesPlanError(f"service #{index} is not an object")
    return RaesPlanServicePort(
        port=_service_port(raw, index),
        protocol=_service_protocol(raw, index),
        name=_service_name(raw, index),
    )


def build_node_services(raw_services: object) -> tuple[RaesPlanServicePort, ...]:
    """Build a node's authored services from a raw ``spec.node.services`` value.

    Absent (``None``) yields no services; a *present* but non-sequence value fails
    closed (ADR-032-R8) rather than being silently ignored. Each entry is parsed
    fail-closed by :func:`_service`, and a duplicate normalized ``(protocol, port)``
    binding raises rather than emitting two overlapping ingress rules -- the separate
    provisioner trust boundary re-checks the SDL uniqueness invariant explicitly.
    """
    if raw_services is None:
        return ()
    if not isinstance(raw_services, list | tuple):
        raise RaesPlanError("node 'services' must be a sequence of service objects")
    services: list[RaesPlanServicePort] = []
    seen: set[tuple[str, int]] = set()
    for index, raw in enumerate(raw_services):
        service = _service(raw, index)
        key = (service.protocol, service.port)
        if key in seen:
            raise RaesPlanError(f"duplicate service binding {service.protocol}/{service.port}")
        seen.add(key)
        services.append(service)
    return tuple(services)
