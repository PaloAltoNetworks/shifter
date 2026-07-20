"""Value types for the range-escape validation suite (issue #1347).

These are the platform-owned, non-secret inputs the runner consumes: the range
under test and its peers, the platform network inventory, the ADR-017 egress
policy, and the probe targets/observations exchanged with the probe-launch
adapter. Targets are always resolved from platform state, never from a
participant-controlled request.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shared.range_escape import BoundaryCode, DestinationClass, Outcome

DEFAULT_MANAGEMENT_PORTS: tuple[int, ...] = (22, 3389)
# The well-known GCP metadata server IP; a required constant, not a config value.
DEFAULT_METADATA_IP = "169.254.169.254"  # NOSONAR
DEFAULT_METADATA_HOST = "metadata.google.internal"


class ProbeKind(StrEnum):
    """How a probe attempts to reach a target."""

    TCP_CONNECT = "tcp_connect"
    DNS_RESOLVE = "dns_resolve"
    METADATA = "metadata"


class ProbeOutcome(StrEnum):
    """The observed result of one probe attempt.

    The suite must never conflate "the boundary blocked me" with "I could not
    test", so a single ``reachable`` boolean is not enough. ``blocked`` (a silent
    drop / timeout) is the only secure outcome for a should-be-unreachable
    boundary; ``refused`` means the packet reached the target host (the path
    exists); ``reachable`` means a connection or resolution succeeded; ``error``
    means the probe could not run (missing tool, execution failure) and is
    inconclusive, never a pass.
    """

    REACHABLE = "reachable"
    REFUSED = "refused"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass(frozen=True)
class ParticipantContext:
    """How the probe-launch adapter reaches a range's participant execution context.

    ``adapter`` selects the launch mechanism (native VM participant SSH, or a
    scenario-owned container exec such as Polaris). Evidence must originate from
    this context, not from the portal or provisioner.
    """

    range_id: int
    request_id: str
    target_ref: str
    address: str
    ssh_port: int
    credential_ref: str
    username: str = "participant"
    # OpenSSH public key line for the guest, from platform provisioning state. The
    # transport pins it so an impostor server cannot return a forged all-secure
    # envelope; an empty value fails the launch (missing identity is not a pass).
    host_public_key: str = ""
    adapter: str = "native"
    container: str = ""


@dataclass(frozen=True)
class RangeUnderTest:
    """A single range's platform-owned validation inputs."""

    range_id: int
    request_id: str
    subnet_cidrs: tuple[str, ...]
    member_ips: tuple[str, ...]
    participant: ParticipantContext
    # Peer-owned DNS names (for example a member's internal DNS identity). A peer's
    # names are the negative target for the cross-range DNS boundary: resolving one
    # of another range's names to a useful route is a leak.
    dns_names: tuple[str, ...] = ()
    management_ports: tuple[int, ...] = DEFAULT_MANAGEMENT_PORTS


@dataclass(frozen=True)
class EgressPolicy:
    """The ADR-017 range egress policy plus operator-owned egress canaries.

    ``canaries`` are operator-owned targets expected to be UNREACHABLE (they prove
    egress is denied). ``allowed_canaries`` are operator-owned, known-live targets
    expected to be REACHABLE under an allowlist policy (they prove the sanctioned
    egress lane works). ``allowed_cidrs`` is the declared policy allowlist; it is not
    probed directly because a policy CIDR is not proof that any host in it is live.
    """

    mode: str
    allowed_cidrs: tuple[str, ...] = ()
    canaries: tuple[str, ...] = ()
    allowed_canaries: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlatformInventory:
    """Non-secret platform network targets resolved from Terraform/runtime outputs."""

    pod_cidr: str
    service_cidr: str
    node_cidr: str
    portal_private_endpoints: tuple[str, ...] = ()
    gke_gdc_api_endpoint: str = ""
    metadata_ip: str = DEFAULT_METADATA_IP
    metadata_host: str = DEFAULT_METADATA_HOST
    private_dns_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeTarget:
    """One bounded attempt the probe should make in participant context."""

    check_id: str
    boundary_code: BoundaryCode
    destination_class: DestinationClass
    kind: ProbeKind
    expected: Outcome
    address: str = ""
    port: int = 0
    hostname: str = ""


@dataclass(frozen=True)
class ObservedProbe:
    """The bounded, non-secret observation the probe returns for one target."""

    outcome: ProbeOutcome
    detail: str = ""
    metadata_credentials_useful: bool | None = None


@dataclass(frozen=True)
class ProbeSpecEntry:
    """A single wire-format probe instruction (bounded, no secrets)."""

    check_id: str
    kind: str
    address: str
    port: int
    hostname: str


def spec_entry_from_target(target: ProbeTarget) -> ProbeSpecEntry:
    """Project a probe target into its bounded wire-format spec entry."""
    return ProbeSpecEntry(
        check_id=target.check_id,
        kind=target.kind.value,
        address=target.address,
        port=target.port,
        hostname=target.hostname,
    )


__all__ = [
    "DEFAULT_MANAGEMENT_PORTS",
    "DEFAULT_METADATA_HOST",
    "DEFAULT_METADATA_IP",
    "EgressPolicy",
    "ObservedProbe",
    "ParticipantContext",
    "PlatformInventory",
    "ProbeKind",
    "ProbeOutcome",
    "ProbeSpecEntry",
    "ProbeTarget",
    "RangeUnderTest",
    "spec_entry_from_target",
]
