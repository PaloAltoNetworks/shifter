"""Top-level CTF range aggregate.

Extends RangeSpecBase with the CTF discriminator. Aggregates the richer
scenario structure that a baseline hospital and its scenario overlays
compose onto.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import field_validator, model_validator

from ..range import RangeSpecBase
from .access import ParticipantAccessSpec
from .asset import AssetSpec
from .data import DataSeedSpec
from .detection import DetectionStackSpec
from .flag import FlagSpec
from .forest import ForestSpec
from .network import NetworkSpec
from .service import ServiceSpec
from .zone import ZoneSpec

if TYPE_CHECKING:  # forward refs for mypy only — runtime uses string types
    pass

CYBERSCRIPT_VERSION_V1 = "v1"


class CTFRangeSpec(RangeSpecBase):
    """A CTF-class range.

    Expresses the shape of a real, scenario-rich range with multi-zone
    topology, multi-forest AD, scenario-layer services, data seeding,
    optional defender stack, and participant access plane.

    Intentional vulnerabilities and planted flags live on scenario
    overlays (ScenarioOverlaySpec), not on the range itself. The
    baseline hospital is a range; a scenario-time deployment is range +
    overlay.

    Attributes:
        range_type: always 'ctf' — discriminator.
        cyberscript_version: always 'v1' today.
        zones: ZoneSpec list.
        networks: NetworkSpec list.
        forests: ForestSpec list.
        services: ServiceSpec list.
        assets: flat AssetSpec list; each asset names its zone.
        flags: FlagSpec list (baseline rarely carries any; overlays do).
        data_seeds: declarative seeding operations.
        detection: optional defender-stack declaration.
        participant_access: per-participant access plane config.

    Notes:
        RangeSpecBase already carries `subnets: list[SubnetSpec]`. For CTF
        ranges, `subnets` stays empty (or carries a placeholder) — the
        CTF surface uses `networks` instead, which the CTF hydrator
        translates to provisioner calls. This keeps the demo-range
        RangeSpecBase field surface intact for AWS continuity (ADR-005).
    """

    range_type: Literal["ctf"] = "ctf"
    cyberscript_version: Literal["v1"] = "v1"

    zones: list[ZoneSpec] = []
    networks: list[NetworkSpec] = []
    forests: list[ForestSpec] = []
    services: list[ServiceSpec] = []
    assets: list[AssetSpec] = []
    flags: list[FlagSpec] = []
    data_seeds: list[DataSeedSpec] = []
    detection: DetectionStackSpec | None = None
    participant_access: ParticipantAccessSpec | None = None

    @field_validator("zones")
    @classmethod
    def zones_nonempty(cls, v: list[ZoneSpec]) -> list[ZoneSpec]:
        if not v:
            raise ValueError("CTF range must declare at least one zone")
        return v

    @model_validator(mode="after")
    def validate_name_references(self) -> CTFRangeSpec:
        """Cross-reference integrity: every name-ref resolves."""
        zone_names = {z.name for z in self.zones}
        network_names = {n.name for n in self.networks}
        asset_names = {a.name for a in self.assets}
        service_names = {s.name for s in self.services}
        forest_names = {f.name for f in self.forests}

        # Zone network references
        for z in self.zones:
            for net_ref in z.networks:
                if net_ref not in network_names:
                    raise ValueError(
                        f"zone {z.name!r} references unknown network {net_ref!r}"
                    )

        # Network zone references
        for n in self.networks:
            if n.zone not in zone_names:
                raise ValueError(f"network {n.name!r} references unknown zone {n.zone!r}")
            for route in n.routes:
                if route.to not in network_names:
                    raise ValueError(
                        f"network {n.name!r} route references unknown network {route.to!r}"
                    )

        # Asset zone + network references
        for a in self.assets:
            if a.zone not in zone_names:
                raise ValueError(f"asset {a.name!r} references unknown zone {a.zone!r}")
            for att in a.networks:
                if att.network not in network_names:
                    raise ValueError(
                        f"asset {a.name!r} attaches to unknown network {att.network!r}"
                    )
            for svc in a.services:
                if svc not in service_names:
                    raise ValueError(
                        f"asset {a.name!r} references unknown service {svc!r}"
                    )
            if a.join_domain is not None and a.join_domain not in forest_names:
                raise ValueError(
                    f"asset {a.name!r} join_domain references unknown forest {a.join_domain!r}"
                )

        # Service asset references
        for s in self.services:
            if s.primary_asset not in asset_names:
                raise ValueError(
                    f"service {s.name!r} primary_asset references unknown asset {s.primary_asset!r}"
                )
            for comp in s.component_assets:
                if comp not in asset_names:
                    raise ValueError(
                        f"service {s.name!r} component_assets references unknown asset {comp!r}"
                    )

        # Forest DC asset references
        for f in self.forests:
            for d in [f.root_domain, *f.child_domains]:
                for dc in d.dc_asset_names:
                    if dc not in asset_names:
                        raise ValueError(
                            f"forest {f.name!r} domain {d.domain_name!r} references unknown DC asset {dc!r}"
                        )
            for t in f.trusts:
                if t.target_forest not in forest_names:
                    raise ValueError(
                        f"forest {f.name!r} trust references unknown forest {t.target_forest!r}"
                    )

        # Flag asset/zone references
        for fl in self.flags:
            if fl.zone not in zone_names:
                raise ValueError(
                    f"flag {fl.id!r} references unknown zone {fl.zone!r}"
                )
            if fl.asset not in asset_names:
                raise ValueError(
                    f"flag {fl.id!r} references unknown asset {fl.asset!r}"
                )
            if fl.service is not None and fl.service not in service_names:
                raise ValueError(
                    f"flag {fl.id!r} references unknown service {fl.service!r}"
                )

        # Data seed service references
        for ds in self.data_seeds:
            # Each variant exposes into_service
            into_service = getattr(ds, "into_service", None)
            if into_service is not None and into_service not in service_names:
                raise ValueError(
                    f"data seed references unknown service {into_service!r}"
                )

        # Participant access network references
        if self.participant_access is not None:
            for kn in self.participant_access.kali_networks:
                if kn not in network_names:
                    raise ValueError(
                        f"participant_access.kali_networks references unknown network {kn!r}"
                    )

        return self

    @model_validator(mode="after")
    def unique_asset_and_flag_ids(self) -> CTFRangeSpec:
        """Asset names and flag ids are unique within the range."""
        asset_names: set[str] = set()
        for a in self.assets:
            if a.name in asset_names:
                raise ValueError(f"duplicate asset name {a.name!r}")
            asset_names.add(a.name)
        flag_ids: set[str] = set()
        for fl in self.flags:
            if fl.id in flag_ids:
                raise ValueError(f"duplicate flag id {fl.id!r}")
            flag_ids.add(fl.id)
        zone_names: set[str] = set()
        for z in self.zones:
            if z.name in zone_names:
                raise ValueError(f"duplicate zone name {z.name!r}")
            zone_names.add(z.name)
        network_names: set[str] = set()
        for n in self.networks:
            if n.name in network_names:
                raise ValueError(f"duplicate network name {n.name!r}")
            network_names.add(n.name)
        return self
