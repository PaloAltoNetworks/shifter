"""One-shot in-guest command execution for the escape-validation suite (issue #1347).

The escape suite must originate its probes from participant context inside a range
cell, not from the portal or provisioner. This helper is the portal-side seam that
opens a single SSH session to a range guest's private address (over the approved
management path) and runs one bounded command, returning its stdout. It reuses the
portal's existing ``asyncssh`` transport (see ``engine.ssh``); it does not import
the standalone provisioner's executors.

The probe program itself carries its own bounded timeouts; ``timeout_s`` bounds the
transport-level wait so a hung guest cannot stall the suite.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import asyncssh


class GuestProbeError(Exception):
    """Raised when the in-guest probe transport fails."""


@dataclass(frozen=True)
class GuestProbeRequest:
    """The cohesive connection + payload inputs for one in-guest probe run."""

    host: str
    username: str
    private_key: str
    host_public_key: str
    command: str
    stdin: str
    port: int = 22
    timeout_s: int = 30


@dataclass(frozen=True)
class RangeMembership:
    """Non-secret, platform-owned membership for a provisioned range.

    This is the service-seam value the cms escape-validation resolver consumes so
    it never imports ``engine.models`` directly (ADR-001). ``instances`` are the
    plain provisioner output dicts (private IP, participant/host SSH references,
    role, uuid); no ORM objects cross the boundary.
    """

    range_id: int
    instances: tuple[dict[str, Any], ...]
    subnet_cidrs: tuple[str, ...]


def get_range_membership(request_id: str) -> RangeMembership | None:
    """Return the provisioned membership + subnet CIDRs for a range, or None.

    Operator/management context: reads the persisted range and its subnet
    allocations. Returns plain data so callers in other layers do not import the
    engine models.
    """
    from engine.models import Range, SubnetAllocation

    range_obj = Range.objects.filter(request__request_id=request_id).order_by("-id").first()
    if range_obj is None:
        return None
    instances = tuple(dict(inst) for inst in (range_obj.provisioned_instances or []) if isinstance(inst, dict))
    subnet_cidrs = tuple(
        sorted({row.cidr for row in SubnetAllocation.objects.filter(request_id=request_id) if row.cidr})
    )
    if not subnet_cidrs and range_obj.subnet_cidr:
        subnet_cidrs = (range_obj.subnet_cidr,)
    return RangeMembership(range_id=range_obj.id, instances=instances, subnet_cidrs=subnet_cidrs)


def run_guest_probe(request: GuestProbeRequest) -> str:
    """Run the probe command in a range guest over SSH, returning stdout.

    ``request.command`` is the delivery wrapper (``bash -s`` for a native VM, or
    ``docker exec -i <container> bash -s`` for a scenario container) and
    ``request.stdin`` the self-contained probe program. ``request.host_public_key``
    is the guest's OpenSSH public key from platform provisioning state; it is pinned
    so an impostor server cannot return a forged all-secure envelope. A missing host
    key, a nonzero remote exit, or any transport error raises :class:`GuestProbeError`
    so the gate treats a probe that did not verifiably run as a failure, never a pass.
    """
    if not request.host_public_key.strip():
        raise GuestProbeError(
            f"missing guest host identity for {request.host}:{request.port}; refusing unverified probe"
        )
    return asyncio.run(_run_guest_probe(request))


async def _run_guest_probe(request: GuestProbeRequest) -> str:
    """Open a host-key-pinned SSH session and run the probe command, returning stdout."""
    try:
        key = asyncssh.import_private_key(request.private_key)
        known_hosts = asyncssh.import_known_hosts(f"{request.host} {request.host_public_key.strip()}\n")
        async with asyncssh.connect(
            request.host,
            port=request.port,
            username=request.username,
            client_keys=[key],
            known_hosts=known_hosts,
        ) as conn:
            result = await conn.run(request.command, input=request.stdin, timeout=request.timeout_s)
    except (asyncssh.Error, OSError, ValueError) as exc:
        # OSError already covers TimeoutError (the asyncssh command timeout).
        raise GuestProbeError(f"in-guest probe transport failed for {request.host}:{request.port}") from exc
    if result.exit_status not in (0, None):
        raise GuestProbeError(f"in-guest probe exited {result.exit_status} for {request.host}:{request.port}")
    return result.stdout if isinstance(result.stdout, str) else ""


__all__ = ["GuestProbeError", "GuestProbeRequest", "RangeMembership", "get_range_membership", "run_guest_probe"]
