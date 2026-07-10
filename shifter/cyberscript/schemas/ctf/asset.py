"""Assets — the superset of InstanceSpec for CTF ranges.

Maps directly to what the GDC provisioner runners
(`shifter/engine/provisioner/gdc_scenario_pods.py`,
`gdc_vmruntime_assets.py`) already consume via `asset_type`. This spec
surface exposes the same values to scenario authors without an in-between
translation layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from ..base import SpecBase
from .safety import SafetyEnvelopeSpec

AssetType = Literal[
    "scenario_pod",
    "vm_runtime_vm",
    "dc_vm",
    "iot_pod",
    "ot_plc_pod",
    "ngfw",
    "shared_service",
]

AssetRole = Literal[
    "attacker",
    "victim",
    "dc",
    "ngfw",
    "iot",
    "ot",
    "shared_service",
]

AssetOSType = Literal[
    "kali",
    "ubuntu",
    "windows",
    "windows_lite",
    "panos",
    "alpine",
    "rocky",
    "debian",
]


class AssetNetworkAttachment(BaseModel):
    """Binding between an asset and a network it participates on.

    Multiple attachments per asset for multi-homing.

    Attributes:
        network: NetworkSpec.name.
        ip: static IP in the network's CIDR; auto-assigned if None.
        interface: interface name (matches gdc_scenario_pods.py convention).
        primary: whether this attachment is the asset's primary net.
    """

    network: str
    ip: str | None = None
    interface: str = "net1"
    primary: bool = False


class DCConfigExt(BaseModel):
    """Domain Controller configuration for dc_vm assets.

    Kept distinct from cyberscript.schemas.range.DCConfig so the CTF
    surface can evolve independently without disturbing the demo range.
    """

    domain_name: str
    netbios_name: str
    functional_level: Literal["2016", "2019", "2022"] = "2022"


class AssetSpec(SpecBase):
    """A single scenario asset (pod, VM, DC VM, PLC pod, etc.).

    Attributes:
        name: unique asset identifier within the range.
        asset_type: provisioner-level asset category.
        role: logical role (superset of legacy InstanceSpec.role).
        os_type: OS or OS-profile.
        zone: ZoneSpec.name that owns this asset.
        networks: list of AssetNetworkAttachment entries (multi-home).
        scope: shared across all participants, or per-participant.
        image: container image (scenario_pod / iot_pod / ot_plc_pod) or
            Packer image key (vm_runtime_vm / dc_vm).
        image_pull_policy: k8s image pull policy (ignored for VMs).
        hostname: DNS-safe hostname; defaults to sanitized name.
        services: ServiceSpec.name references for scenario-layer services
            this asset participates in.
        tags: arbitrary tags (used by overlays and CTFd authoring).
        dc_config: required when asset_type == "dc_vm".
        join_domain: ForestSpec.name of the forest this asset joins.
        safety_envelope: required when role == "ot"; declares safe
            register ranges for the emulator.
    """

    name: str
    asset_type: AssetType
    role: AssetRole
    os_type: AssetOSType
    zone: str
    networks: list[AssetNetworkAttachment] = []
    scope: Literal["shared", "per_participant"] = "per_participant"
    image: str | None = None
    image_pull_policy: Literal["IfNotPresent", "Always", "Never"] = "IfNotPresent"
    hostname: str | None = None
    services: list[str] = []
    tags: list[str] = []
    dc_config: DCConfigExt | None = None
    join_domain: str | None = None
    safety_envelope: SafetyEnvelopeSpec | None = None

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("asset name must be non-empty")
        return v.strip()

    @model_validator(mode="after")
    def validate_type_role_consistency(self) -> AssetSpec:
        """Ensure asset_type, role, and required blocks line up."""
        if self.asset_type == "dc_vm":
            if self.role != "dc":
                raise ValueError("dc_vm asset_type requires role='dc'")
            if self.dc_config is None:
                raise ValueError("dc_vm asset requires dc_config")
            if self.os_type not in ("windows", "windows_lite"):
                raise ValueError("dc_vm asset requires os_type in {'windows','windows_lite'}")
        if self.role == "ot" and self.safety_envelope is None:
            raise ValueError(
                f"asset {self.name!r} has role='ot' and must declare safety_envelope"
            )
        if self.asset_type == "ngfw" and self.role != "ngfw":
            raise ValueError("asset_type='ngfw' requires role='ngfw'")
        return self

    @model_validator(mode="after")
    def validate_one_primary_network(self) -> AssetSpec:
        """At most one attachment may be marked primary."""
        primaries = [a for a in self.networks if a.primary]
        if len(primaries) > 1:
            raise ValueError(
                f"asset {self.name!r} must have at most one primary network attachment"
            )
        return self
