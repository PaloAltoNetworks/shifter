"""Typed option and runtime bindings for RAES-native GCE apply."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from config import GCERangeCellConfig
from gcp_range_cell_clients import GCEClients
from raes_account_credentials import RaesAccountCredentialOps, install_instance_account_credentials
from raes_active_directory import RaesDirectorySecretOps, realize_raes_active_directory
from raes_composition_verification import verify_bootstrap_composition
from raes_content_delivery import realize_raes_content_delivery
from raes_gcp_secret_ops import RaesGceSecretOps
from raes_operating_system import observe_operating_systems
from raes_preconfigured_host_readiness import verify_preconfigured_hosts
from raes_substrate_observation import observe_gce_substrates

if TYPE_CHECKING:
    from raes_gcp_vpn_plan import RaesGceVpnAccess


class RaesGceOpenVpn(Protocol):
    """A generation's prepared participant OpenVPN access (#2030, ``raes_openvpn``)."""

    def plan_access(self) -> RaesGceVpnAccess:
        """Return the pool firewall inputs for this range."""

    def publish(self) -> dict[str, object]:
        """Mint the generation's profile and return the owner-free realization."""


@dataclass(frozen=True)
class RaesGceApplyOptions:
    """Optional infrastructure and credential bindings for an RAES apply."""

    config: GCERangeCellConfig | None = None
    clients: GCEClients | None = None
    secret_ops: RaesGceSecretOps | None = None
    egress_mode: str = "status-quo"
    allocated_network_cidrs: Sequence[tuple[str, str]] | None = None
    on_pre_mutation_failure: Callable[[], None] | None = None
    account_secret_ops: RaesAccountCredentialOps | None = None
    credential_installer: Callable[..., dict[str, str]] = install_instance_account_credentials
    directory_secret_ops: RaesDirectorySecretOps | None = None
    directory_realizer: Callable[..., None] = realize_raes_active_directory
    content_delivery_realizer: Callable[..., None] = realize_raes_content_delivery
    composition_verifier: Callable[..., frozenset[str]] = verify_bootstrap_composition
    operating_system_observer: Callable[..., list[dict[str, str]]] = observe_operating_systems
    substrate_observer: Callable[..., list[dict[str, str]]] = observe_gce_substrates
    host_readiness_verifier: Callable[[list[dict[str, object]]], None] = verify_preconfigured_hosts

    runtime_plugin: Callable[..., None] | None = None
    model_enrollment: Callable[..., None] | None = None
    model_broker: dict[str, object] | None = None
    openvpn: RaesGceOpenVpn | None = None


@dataclass(frozen=True)
class RaesGceApplyRuntime:
    """Resolved non-optional bindings shared by RAES resource realization."""

    config: GCERangeCellConfig
    clients: GCEClients
    secret_ops: RaesGceSecretOps
    account_secret_ops: RaesAccountCredentialOps
    credential_installer: Callable[..., dict[str, str]]
    directory_secret_ops: RaesDirectorySecretOps
    directory_realizer: Callable[..., None]
    content_delivery_realizer: Callable[..., None]
    composition_verifier: Callable[..., frozenset[str]]
    operating_system_observer: Callable[..., list[dict[str, str]]]
    substrate_observer: Callable[..., list[dict[str, str]]]
    host_readiness_verifier: Callable[[list[dict[str, object]]], None]
    allocated_network_cidrs: Sequence[tuple[str, str]] | None
    runtime_plugin: Callable[..., None] | None
    model_enrollment: Callable[..., None] | None
    openvpn: RaesGceOpenVpn | None = None
