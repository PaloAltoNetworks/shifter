"""Resolve a range's platform-owned validation inputs (issue #1347).

The runner consumes non-secret, platform-owned inputs; this module is the seam
that builds them from portal state. Range membership and the participant access
context come from the ``engine.services.get_range_membership`` service seam (so cms
never imports the engine models, per ADR-001). The platform network inventory and
the ADR-017 egress policy are deployment facts supplied by the operator/CI config,
not read from a participant-controlled request.

The pure instance-selection and config helpers are unit tested; the membership
lookup is validated against a live range.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from cms.range_escape.model import (
    DEFAULT_METADATA_HOST,
    DEFAULT_METADATA_IP,
    EgressPolicy,
    ParticipantContext,
    PlatformInventory,
    RangeUnderTest,
)

_ATTACKER_ROLES = frozenset({"attacker", "kali"})


class RangeResolutionError(Exception):
    """Raised when a range cannot be resolved into validation inputs."""


def resolve_range_under_test(*, request_id: str, adapter: str = "native", container: str = "") -> RangeUnderTest:
    """Resolve a provisioned range into a :class:`RangeUnderTest` (operator context)."""
    from engine.services import get_range_membership

    membership = get_range_membership(request_id)
    if membership is None:
        raise RangeResolutionError(f"no range found for request {request_id}")
    if not membership.instances:
        raise RangeResolutionError(f"range for request {request_id} has no provisioned instances")

    member_ips = tuple(str(inst["private_ip"]) for inst in membership.instances if inst.get("private_ip"))
    participant = _participant_from_instances(
        membership.instances, range_id=membership.range_id, request_id=request_id, adapter=adapter, container=container
    )
    return RangeUnderTest(
        range_id=membership.range_id,
        request_id=request_id,
        subnet_cidrs=tuple(membership.subnet_cidrs),
        member_ips=member_ips,
        participant=participant,
        dns_names=_dns_names_from_instances(membership.instances),
    )


def _dns_names_from_instances(instances: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Derive each member's internal GCP DNS name (a peer-owned identity).

    A member's zonal internal DNS name resolves only inside its own network scope;
    another range resolving it to a useful route is a cross-range DNS leak.
    """
    names: list[str] = []
    for inst in instances:
        name = str(inst.get("gcp_instance_name") or "")
        zone = str(inst.get("gcp_zone") or "")
        project = str(inst.get("gcp_project_id") or "")
        if name and zone and project:
            names.append(f"{name}.{zone}.c.{project}.internal")
    return tuple(names)


def _participant_from_instances(
    instances: Sequence[Mapping[str, Any]],
    *,
    range_id: int,
    request_id: str,
    adapter: str,
    container: str,
) -> ParticipantContext:
    """Build the participant context from the selected instance for the adapter."""
    inst = _pick_participant_instance(instances)
    address = str(inst.get("private_ip") or "")
    if not address:
        raise RangeResolutionError("participant instance has no private IP")
    port, credential_ref, username = _participant_access(inst, adapter)
    if not credential_ref:
        raise RangeResolutionError("participant instance has no SSH credential reference")
    return ParticipantContext(
        range_id=range_id,
        request_id=request_id,
        target_ref=str(inst.get("uuid") or ""),
        address=address,
        ssh_port=port,
        credential_ref=credential_ref,
        username=username,
        host_public_key=str(inst.get("gcp_host_public_key") or ""),
        adapter=adapter,
        container=container,
    )


def _participant_access(inst: Mapping[str, Any], adapter: str) -> tuple[int, str, str]:
    """Return (ssh_port, credential_ref, username) for the adapter's access channel.

    The Polaris adapter reaches the participant container over the Docker host's
    management SSH; the native adapter uses the participant SSH channel directly.
    """
    if adapter == "polaris":
        return (
            int(inst.get("gcp_host_ssh_port") or 22),
            str(inst.get("gcp_host_ssh_key_secret_ref") or inst.get("ssh_key_secret_arn") or ""),
            str(inst.get("gcp_host_ssh_username") or inst.get("ssh_username") or "participant"),
        )
    return (22, str(inst.get("ssh_key_secret_arn") or ""), str(inst.get("ssh_username") or "participant"))


def _pick_participant_instance(instances: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Choose the instance whose context best represents a participant.

    Prefer an attacker-role guest with a participant SSH channel, then any guest
    with a participant SSH channel, then the first guest. This is scenario-neutral:
    it keys on the presence of a participant credential, not on scenario topology.
    """
    for inst in instances:
        if inst.get("ssh_key_secret_arn") and str(inst.get("role", "")).lower() in _ATTACKER_ROLES:
            return inst
    for inst in instances:
        if inst.get("ssh_key_secret_arn"):
            return inst
    if instances:
        return instances[0]
    raise RangeResolutionError("range has no participant instance")


def platform_inventory_from_config(config: Mapping[str, Any]) -> PlatformInventory:
    """Build the platform network inventory from an operator-supplied config mapping."""
    platform = config.get("platform")
    if not isinstance(platform, Mapping):
        raise RangeResolutionError("config.platform must be an object with the platform network inventory")
    try:
        return PlatformInventory(
            pod_cidr=str(platform["pod_cidr"]),
            service_cidr=str(platform["service_cidr"]),
            node_cidr=str(platform["node_cidr"]),
            portal_private_endpoints=tuple(str(e) for e in platform.get("portal_private_endpoints", [])),
            gke_gdc_api_endpoint=str(platform.get("gke_gdc_api_endpoint", "")),
            metadata_ip=str(platform.get("metadata_ip", DEFAULT_METADATA_IP)),
            metadata_host=str(platform.get("metadata_host", DEFAULT_METADATA_HOST)),
            private_dns_names=tuple(str(n) for n in platform.get("private_dns_names", [])),
        )
    except KeyError as exc:
        raise RangeResolutionError(f"config.platform is missing required field: {exc}") from exc


def egress_policy_from_config(config: Mapping[str, Any]) -> EgressPolicy:
    """Build the ADR-017 egress policy plus operator canaries from config."""
    egress = config.get("egress")
    if not isinstance(egress, Mapping):
        raise RangeResolutionError("config.egress must be an object with the range egress policy")
    return EgressPolicy(
        mode=str(egress.get("mode", "deny-all")),
        allowed_cidrs=tuple(str(c) for c in egress.get("allowed_cidrs", [])),
        canaries=tuple(str(c) for c in egress.get("canaries", [])),
        allowed_canaries=tuple(str(c) for c in egress.get("allowed_canaries", [])),
    )


__all__ = [
    "RangeResolutionError",
    "egress_policy_from_config",
    "platform_inventory_from_config",
    "resolve_range_under_test",
]
