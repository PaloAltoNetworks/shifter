"""Value objects + error for the provisioner-side serialized RAES plan (ADR-031, ADR-032).

Split out of ``raes_plan`` (Sonar file-size, mirroring ``raes_composition``): the
frozen dataclasses the provisioner reconstructs from the serialized RAES
ProvisioningPlan, plus the single ``RaesPlanError`` raised throughout parsing.
Pure data (no ``raes_*`` SDL import, no Pydantic); the composition value objects
(``RaesPlanContent`` / ``RaesPlanAccount`` / ``RaesPlanFeature``) live in
``raes_composition`` and are re-used by :class:`RaesPlan`.
"""

from __future__ import annotations

from dataclasses import dataclass

from raes_composition import RaesPlanAccount, RaesPlanContent, RaesPlanFeature

__all__ = [
    "RaesPlan",
    "RaesPlanAcl",
    "RaesPlanDomain",
    "RaesPlanError",
    "RaesPlanImage",
    "RaesPlanNetwork",
    "RaesPlanNode",
    "RaesPlanServicePort",
]


class RaesPlanError(ValueError):
    """Raised when a persisted range_config is not a well-formed serialized RAES plan."""


@dataclass(frozen=True)
class RaesPlanImage:
    """Authored image reference (from RAES ``source``); resolved to a concrete
    provider image by the backend at realization (ADR-032-R2)."""

    name: str
    version: str | None = None


@dataclass(frozen=True)
class RaesPlanAcl:
    """A node's authored network ACL (mirror raes_backend_libvirt.acls fields).

    ``action`` is normalized to ``accept``/``drop`` and ``protocol`` to
    ``tcp``/``udp``/``all``; ``from_net``/``to_net`` are kept as the authored
    network refs (resolved to concrete CIDRs at realization, fail-closed, so an
    unresolvable *specified* endpoint is never widened into a broad allow).
    """

    name: str
    action: str
    direction: str
    protocol: str
    ports: tuple[int, ...]
    from_net: str | None = None
    to_net: str | None = None


@dataclass(frozen=True)
class RaesPlanServicePort:
    """A node's authored service port (RAES ``ServicePort`` / OCSF NetworkEndpoint).

    Layer-4 transport-exposure intent, realized as fail-closed per-node-tag ingress
    by the GCE backend (ADR-032-R8). ``protocol`` is normalized to ``tcp``/``udp``
    and ``port`` is a concrete ``1..65535`` integer; ``name`` is retained for stable
    ordering / diagnostics only, never for provider resource identity.
    """

    port: int
    protocol: str
    name: str = ""


@dataclass(frozen=True)
class RaesPlanNode:
    """A compute node to provision, with authored intent extracted verbatim."""

    address: str
    name: str
    os_family: str
    count: int
    network_addresses: tuple[str, ...]
    # Canonical network address -> authored IPv4 address pairs extracted from
    # RAES 3.5 ``spec.infrastructure.properties``.  This remains authored intent;
    # provider adapters rebase the host offset into their realized subnet.
    network_ip_assignments: tuple[tuple[str, str], ...] = ()
    # True only when the portable plan leaves network selection to the
    # realizer.  An explicitly present, empty network list remains closed and
    # must not be silently defaulted by a provider adapter.
    network_selection_open: bool = False
    ram_mib: int | None = None
    vcpus: int | None = None
    image: RaesPlanImage | None = None
    acls: tuple[RaesPlanAcl, ...] = ()
    services: tuple[RaesPlanServicePort, ...] = ()
    ordering_dependencies: tuple[str, ...] = ()
    domain_id: str | None = None
    domain_role: str | None = None
    controller_addresses: tuple[str, ...] = ()
    domain_profile: str | None = None
    domain_dns_name: str | None = None
    domain_netbios_name: str | None = None
    authority_account_address: str | None = None
    os_distribution: str | None = None
    os_version: str | None = None


@dataclass(frozen=True)
class RaesPlanDomain:
    """Process-local projection of one public compiled identity-domain binding."""

    domain_id: str
    profile: str
    dns_name: str
    netbios_name: str
    authority_account_address: str
    controller_addresses: tuple[str, ...]
    member_addresses: tuple[str, ...]


@dataclass(frozen=True)
class RaesPlanNetwork:
    """A network the range's nodes attach to."""

    address: str
    name: str
    cidr: str | None = None
    gateway: str | None = None
    internal: bool = False


@dataclass(frozen=True)
class RaesPlan:
    """The parsed serialized RAES plan: nodes + networks + composition for realization."""

    raes_version: str
    nodes: tuple[RaesPlanNode, ...]
    networks: tuple[RaesPlanNetwork, ...]
    content: tuple[RaesPlanContent, ...] = ()
    accounts: tuple[RaesPlanAccount, ...] = ()
    features: tuple[RaesPlanFeature, ...] = ()
    domains: tuple[RaesPlanDomain, ...] = ()
