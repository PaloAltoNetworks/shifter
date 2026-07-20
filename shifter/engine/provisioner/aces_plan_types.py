"""Value objects + error for the provisioner-side serialized ACES plan (ADR-031, ADR-032).

Split out of ``aces_plan`` (Sonar file-size, mirroring ``aces_composition``): the
frozen dataclasses the provisioner reconstructs from the serialized ACES
ProvisioningPlan, plus the single ``AcesPlanError`` raised throughout parsing.
Pure data (no ``aces_*`` SDL import, no Pydantic); the composition value objects
(``AcesPlanContent`` / ``AcesPlanAccount`` / ``AcesPlanFeature``) live in
``aces_composition`` and are re-used by :class:`AcesPlan`.
"""

from __future__ import annotations

from dataclasses import dataclass

from aces_composition import AcesPlanAccount, AcesPlanContent, AcesPlanFeature

__all__ = [
    "AcesPlan",
    "AcesPlanAcl",
    "AcesPlanDomain",
    "AcesPlanError",
    "AcesPlanImage",
    "AcesPlanNetwork",
    "AcesPlanNode",
    "AcesPlanServicePort",
]


class AcesPlanError(ValueError):
    """Raised when a persisted range_config is not a well-formed serialized ACES plan."""


@dataclass(frozen=True)
class AcesPlanImage:
    """Authored image reference (from ACES ``source``); resolved to a concrete
    provider image by the backend at realization (ADR-032-R2)."""

    name: str
    version: str | None = None


@dataclass(frozen=True)
class AcesPlanAcl:
    """A node's authored network ACL (mirror aces_backend_libvirt.acls fields).

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
class AcesPlanServicePort:
    """A node's authored service port (ACES ``ServicePort`` / OCSF NetworkEndpoint).

    Layer-4 transport-exposure intent, realized as fail-closed per-node-tag ingress
    by the GCE backend (ADR-032-R8). ``protocol`` is normalized to ``tcp``/``udp``
    and ``port`` is a concrete ``1..65535`` integer; ``name`` is retained for stable
    ordering / diagnostics only, never for provider resource identity.
    """

    port: int
    protocol: str
    name: str = ""


@dataclass(frozen=True)
class AcesPlanNode:
    """A compute node to provision, with authored intent extracted verbatim."""

    address: str
    name: str
    os_family: str
    count: int
    network_addresses: tuple[str, ...]
    ram_mib: int | None = None
    vcpus: int | None = None
    image: AcesPlanImage | None = None
    acls: tuple[AcesPlanAcl, ...] = ()
    services: tuple[AcesPlanServicePort, ...] = ()
    ordering_dependencies: tuple[str, ...] = ()
    domain_id: str | None = None
    domain_role: str | None = None
    controller_addresses: tuple[str, ...] = ()
    domain_profile: str | None = None
    domain_dns_name: str | None = None
    domain_netbios_name: str | None = None
    authority_account_address: str | None = None


@dataclass(frozen=True)
class AcesPlanDomain:
    """Process-local projection of one public compiled identity-domain binding."""

    domain_id: str
    profile: str
    dns_name: str
    netbios_name: str
    authority_account_address: str
    controller_addresses: tuple[str, ...]
    member_addresses: tuple[str, ...]


@dataclass(frozen=True)
class AcesPlanNetwork:
    """A network the range's nodes attach to."""

    address: str
    name: str
    cidr: str | None = None
    gateway: str | None = None
    internal: bool = False


@dataclass(frozen=True)
class AcesPlan:
    """The parsed serialized ACES plan: nodes + networks + composition for realization."""

    aces_sdl_version: str
    nodes: tuple[AcesPlanNode, ...]
    networks: tuple[AcesPlanNetwork, ...]
    content: tuple[AcesPlanContent, ...] = ()
    accounts: tuple[AcesPlanAccount, ...] = ()
    features: tuple[AcesPlanFeature, ...] = ()
    domains: tuple[AcesPlanDomain, ...] = ()
