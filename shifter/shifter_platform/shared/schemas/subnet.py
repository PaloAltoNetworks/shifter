"""Subnet DSL schemas for network topology.

These Pydantic models define the Subnet DSL - a layered schema system where:
- SubnetSpec defines a logical network segment containing instances
- Projections (SubnetContext, SubnetRef) provide tailored views

Subnets group instances for routing policy purposes. When a range has an NGFW,
inter-subnet traffic flows through it based on defined routes.
"""

from __future__ import annotations

import uuid as uuid_module
from typing import Any

from pydantic import BaseModel, field_validator

from .base import SpecBase


class SubnetSpec(SpecBase):
    """Specification for a logical subnet.

    A subnet groups instances that share network visibility.
    Instances in the same subnet can communicate freely.
    Inter-subnet communication requires explicit connection declarations.

    Connections are bidirectional by default. If subnet A lists subnet B
    in connected_to, both A->B and B->A traffic is allowed. The connection
    only needs to be declared on one side.

    When NGFW is present, connections become firewall rules.
    Without NGFW, connections define logical reachability.

    Attributes:
        name: Subnet name (e.g., 'dc_network', 'server_network').
        uuid: Unique identifier (inherited from SpecBase, assigned during hydration).
        instances: List of instance names belonging to this subnet.
        connected_to: List of subnet names this subnet can reach (bidirectional).
    """

    name: str  # Required for subnets (overrides optional in SpecBase)
    instances: list[str]
    connected_to: list[str] = []

    @field_validator("instances")
    @classmethod
    def instances_not_empty(cls, v: list[str]) -> list[str]:
        """Validate instances list is not empty."""
        if not v:
            raise ValueError("subnet must contain at least one instance")
        return v

    @classmethod
    def from_template(cls, data: dict[str, Any]) -> SubnetSpec:
        """Create a SubnetSpec from a scenario template dict.

        Args:
            data: Template dict with keys: name, instances, connected_to.

        Returns:
            Hydrated SubnetSpec with UUID assigned.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        name = data.get("name")
        instances = data.get("instances")

        if not name:
            raise ValueError("Subnet template requires 'name' field")
        if not instances:
            raise ValueError("Subnet template requires 'instances' field")

        return cls(
            name=name,
            uuid=str(uuid_module.uuid4()),
            instances=instances,
            connected_to=data.get("connected_to", []),
        )


class SubnetContext(BaseModel):
    """Subnet projection for templates.

    Used by Mission Control for rendering subnet information.
    Excludes internal details not needed for display.

    Attributes:
        uuid: Unique identifier of the subnet.
        name: Subnet name.
        instances: List of instance names in this subnet.
        connected_to: List of subnet names this subnet can reach.
    """

    uuid: str
    name: str
    instances: list[str]
    connected_to: list[str] = []

    @field_validator("uuid")
    @classmethod
    def uuid_not_empty(cls, v: str) -> str:
        """Validate uuid is not empty."""
        if not v or not v.strip():
            raise ValueError("uuid cannot be empty")
        return v


class SubnetRef(BaseModel):
    """Minimal subnet reference for operations.

    Contains only identifiers needed to reference a subnet.
    Used for routing operations and status checks.

    Attributes:
        uuid: Unique identifier of the subnet.
        name: Subnet name (for NGFW address object operations).
    """

    uuid: str
    name: str

    @field_validator("uuid")
    @classmethod
    def uuid_not_empty(cls, v: str) -> str:
        """Validate uuid is not empty."""
        if not v or not v.strip():
            raise ValueError("uuid cannot be empty")
        return v
