"""Pydantic models for scenario template validation.

These models define the schema for scenario YAML templates stored in
cms/scenarios/templates/. They provide type validation and default values.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class AgentRequirements(BaseModel):
    """Agent requirements for a scenario.

    Attributes:
        required: Whether an agent is required for this scenario.
        os: OS constraint for the agent (None = any OS accepted).
    """

    required: bool
    os: str | None = None


class DCConfig(BaseModel):
    """Domain Controller configuration.

    Attributes:
        domain_name: Full domain name (e.g., 'lab.local').
        netbios_name: NetBIOS domain name (e.g., 'LAB').
    """

    domain_name: str
    netbios_name: str


class InstanceConfig(BaseModel):
    """Configuration for a single instance in a scenario.

    Attributes:
        role: Instance role (attacker, victim, dc).
        os_type: OS type (kali, windows, ubuntu, from_agent).
        agent_slot: Which agent to use (primary, secondary, None).
        domain_controller: Whether this instance is a domain controller.
        join_domain: Whether this instance should join the domain.
        dc_config: Domain controller configuration (if domain_controller=True).
    """

    role: str
    os_type: str
    agent_slot: str | None = None
    domain_controller: bool = False
    join_domain: bool = False
    dc_config: DCConfig | None = None


class ScenarioTemplate(BaseModel):
    """Complete scenario template definition.

    Attributes:
        id: Unique scenario identifier (e.g., 'basic', 'ad_attack_lab').
        name: Human-readable display name.
        description: User-facing description of the scenario.
        requirements: Agent requirements for the scenario.
        instances: List of instance configurations.
    """

    id: str
    name: str
    description: str
    requirements: AgentRequirements
    instances: list[InstanceConfig]

    @field_validator("instances")
    @classmethod
    def instances_not_empty(cls, v: list[InstanceConfig]) -> list[InstanceConfig]:
        """Validate that instances list is not empty."""
        if not v:
            raise ValueError("instances must not be empty")
        return v
