"""AD forest and trust declarations for CTF ranges.

Models multi-forest scenarios including two-way trusts between a parent
forest and its research-wing child, and external trusts to vendor
forests. Concrete hospital fiction is St. Aurora:

  aurora-med.local  <-- two-way --> research.aurora-med.local
  aurora-med.local  <-- external --> boreas-med.local
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from ..base import SpecBase


class DomainSpec(BaseModel):
    """A single AD domain within a forest.

    Attributes:
        domain_name: FQDN (e.g. "aurora-med.local").
        netbios_name: short NetBIOS name (e.g. "AURORAMED").
        functional_level: domain/forest functional level.
        dc_asset_names: AssetSpec.name refs (must be asset_type=='dc_vm').
    """

    domain_name: str
    netbios_name: str
    functional_level: Literal["2016", "2019", "2022"] = "2022"
    dc_asset_names: list[str]

    @field_validator("domain_name")
    @classmethod
    def domain_name_nonempty(cls, v: str) -> str:
        if not v or "." not in v:
            raise ValueError("domain_name must be a FQDN with at least one dot")
        return v.strip().lower()

    @field_validator("netbios_name")
    @classmethod
    def netbios_upper(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("netbios_name must be non-empty")
        if len(v) > 15:
            raise ValueError("netbios_name must be <= 15 characters")
        return v

    @field_validator("dc_asset_names")
    @classmethod
    def at_least_one_dc(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("domain must reference at least one DC asset")
        return v


class ForestTrustSpec(BaseModel):
    """A trust relationship between forests.

    Attributes:
        target_forest: ForestSpec.name of the peer forest.
        kind: direction of the trust.
        transitive: whether the trust is transitive (typical for two-way;
            external vendor trusts are usually non-transitive).
        rationale: narrative justification for reviewers.
    """

    target_forest: str
    kind: Literal["one_way_out", "one_way_in", "two_way"]
    transitive: bool = True
    rationale: str | None = None


class ForestSpec(SpecBase):
    """A single AD forest.

    Attributes:
        name: logical forest name (e.g. "aurora-med").
        root_domain: the root domain of this forest.
        child_domains: optional child domains.
        trusts: outbound trust relationships.
    """

    name: str
    root_domain: DomainSpec
    child_domains: list[DomainSpec] = []
    trusts: list[ForestTrustSpec] = []

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("forest name must be non-empty")
        return v.strip()

    @model_validator(mode="after")
    def no_self_trust(self) -> ForestSpec:
        for t in self.trusts:
            if t.target_forest == self.name:
                raise ValueError(f"forest {self.name!r} declares a trust to itself")
        return self
