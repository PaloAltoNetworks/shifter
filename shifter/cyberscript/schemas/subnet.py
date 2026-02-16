"""Subnet DSL schemas for network topology.

These Pydantic models define the Subnet DSL - a layered schema system where:
- SubnetSpec defines a logical network segment containing instances
- Projections (SubnetContext, SubnetRef) provide tailored views

Subnets group instances for routing policy purposes. When a range has an NGFW,
inter-subnet traffic flows through it based on defined routes.
"""

from __future__ import annotations

import uuid as uuid_module
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, field_validator

from .base import SpecBase

if TYPE_CHECKING:
    from .range import InstanceSpec


class SubnetSpec(SpecBase):
    """Specification for a logical subnet.

    A subnet groups instances that share network visibility.
    Instances in the same subnet can communicate freely.
    Inter-subnet communication requires explicit connection declarations.

    Connections are unidirectional. If subnet A lists subnet B in connected_to,
    instances in A can initiate connections TO B. For bidirectional communication,
    both subnets must list each other in their connected_to lists.

    When NGFW is present, connections become firewall rules.
    Without NGFW, connections define logical reachability via security groups.

    Attributes:
        name: Subnet name (e.g., 'dc_network', 'server_network').
        uuid: Unique identifier (inherited from SpecBase, assigned during hydration).
        instances: List of InstanceSpecs belonging to this subnet.
        connected_to: List of subnet names this subnet needs to reach.
    """

    name: str  # Required for subnets (overrides optional in SpecBase)
    instances: list[InstanceSpec]
    connected_to: list[str] = []

    @field_validator("instances")
    @classmethod
    def instances_not_empty(cls, v: list) -> list:
        """Validate instances list is not empty."""
        if not v:
            raise ValueError("subnet must contain at least one instance")
        return v

    @classmethod
    def from_template(
        cls,
        data: dict[str, Any],
        instances_by_name: dict[str, InstanceSpec],
    ) -> SubnetSpec:
        """Create a SubnetSpec from a scenario template dict.

        Args:
            data: Template dict with keys: name, instances (names), connected_to.
            instances_by_name: Mapping of instance name to hydrated InstanceSpec.

        Returns:
            Hydrated SubnetSpec with UUID assigned and InstanceSpecs embedded.

        Raises:
            ValueError: If required fields are missing or instance not found.
        """
        name = data.get("name")
        instance_names = data.get("instances")

        if not name:
            raise ValueError("Subnet template requires 'name' field")
        if not instance_names:
            raise ValueError("Subnet template requires 'instances' field")

        # Look up each instance by name
        instances: list[InstanceSpec] = []
        for inst_name in instance_names:
            if inst_name not in instances_by_name:
                raise ValueError(f"Subnet '{name}' references unknown instance '{inst_name}'")
            instances.append(instances_by_name[inst_name])

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


# NOTE: Model rebuilds moved to shared/schemas/__init__.py to avoid circular imports
