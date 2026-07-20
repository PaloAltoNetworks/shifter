"""Network topology for CTF ranges — GDC-aware.

Extends the demo-range SubnetSpec concept with GDC L2 NetworkAttachmentDefinition
attributes, explicit cross-network routes, and zone membership.
"""

from __future__ import annotations

import ipaddress
from typing import Literal

from pydantic import BaseModel, field_validator

from ..base import SpecBase


class GDCNetworkBinding(BaseModel):
    """GDC-specific network attributes.

    Today CTF ranges run only on GDC. Other providers would add their
    own binding type via an Annotated discriminated union.

    Attributes:
        nad_name: NetworkAttachmentDefinition name in the host cluster.
        vlan_id: VLAN identifier if the cluster fabric is VLAN-aware.
        cidr: CIDR block (e.g. "10.20.10.0/24").
        gateway: optional gateway IP (usually .1 of the CIDR).
    """

    nad_name: str
    vlan_id: int | None = None
    cidr: str
    gateway: str | None = None

    @field_validator("cidr")
    @classmethod
    def cidr_valid(cls, v: str) -> str:
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid CIDR: {v!r}") from exc
        return v

    @field_validator("gateway")
    @classmethod
    def gateway_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ipaddress.ip_address(v)
        except ValueError as exc:
            raise ValueError(f"invalid gateway address: {v!r}") from exc
        return v

    @field_validator("vlan_id")
    @classmethod
    def vlan_id_range(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1 or v > 4094:
            raise ValueError("vlan_id must be in [1, 4094]")
        return v


class NetworkRouteSpec(BaseModel):
    """An explicit cross-network route.

    By default unidirectional (from the network declaring it to `to`).
    Set bidirectional=True to mean "mutual reachability."

    Attributes:
        to: peer NetworkSpec.name.
        bidirectional: if True, peer gets the symmetric allow.
        rationale: why this route exists (reviewer-facing).
    """

    to: str
    bidirectional: bool = False
    rationale: str | None = None


class NetworkSpec(SpecBase):
    """A logical network (L2 segment) in a CTF range.

    Attributes:
        name: unique network identifier.
        zone: owning ZoneSpec.name.
        gdc: GDC binding (today GDC-only).
        routes: explicit cross-network route declarations.
        isolation: intra-zone policy default — default_deny or allow_all_within_zone.
    """

    name: str
    zone: str
    gdc: GDCNetworkBinding
    routes: list[NetworkRouteSpec] = []
    isolation: Literal["default_deny", "allow_all_within_zone"] = "default_deny"

    @field_validator("name")
    @classmethod
    def name_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("network name must be non-empty")
        return v.strip()
