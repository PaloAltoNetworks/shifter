"""Pydantic models for scenario template validation.

These models define the schema for scenario YAML templates stored in
cms/scenarios/templates/. They provide type validation and default values.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator


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
        name: Instance display name (e.g., 'Attacker', 'Domain Controller').
        role: Instance role (attacker, victim, dc).
        os_type: OS type (kali, windows, ubuntu, from_agent).
        xdr_agent: Whether to install XDR agent on this instance.
        domain_controller: Whether this instance is a domain controller.
        join_domain: Whether this instance should join the domain.
        dc_config: Domain controller configuration (if domain_controller=True).
    """

    name: str
    role: str
    os_type: str
    xdr_agent: bool = False
    domain_controller: bool = False
    join_domain: bool = False
    dc_config: DCConfig | None = None


class SubnetConfig(BaseModel):
    """Subnet definition in a scenario template.

    Attributes:
        name: Subnet name (e.g., 'dc_network', 'attacker_network').
        instances: List of instance names belonging to this subnet.
        connected_to: List of subnet names this subnet can communicate with.
    """

    name: str
    instances: list[str]
    connected_to: list[str] = []

    @field_validator("instances")
    @classmethod
    def instances_not_empty(cls, v: list[str]) -> list[str]:
        """Validate that instances list is not empty."""
        if not v:
            raise ValueError("subnet must contain at least one instance")
        return v


class ScenarioTemplate(BaseModel):
    """Complete scenario template definition.

    Attributes:
        id: Unique scenario identifier (e.g., 'basic', 'ad_attack_lab').
        name: Human-readable display name.
        description: User-facing description of the scenario.
        enabled: Whether scenario is visible in the UI (default True).
        ngfw: Whether scenario requires NGFW provisioning.
        instances: List of instance configurations.
        subnets: List of subnet configurations (optional).
    """

    id: str
    name: str
    description: str
    enabled: bool = True
    ngfw: bool = False
    instances: list[InstanceConfig]
    subnets: list[SubnetConfig] = []

    @field_validator("instances")
    @classmethod
    def instances_not_empty(cls, v: list[InstanceConfig]) -> list[InstanceConfig]:
        """Validate that instances list is not empty."""
        if not v:
            raise ValueError("instances must not be empty")
        return v

    @model_validator(mode="after")
    def validate_subnet_instances(self) -> ScenarioTemplate:
        """Validate all subnet instance names exist in instances list."""
        instance_names = {i.name for i in self.instances}
        for subnet in self.subnets:
            for inst in subnet.instances:
                if inst not in instance_names:
                    raise ValueError(f"Subnet '{subnet.name}' references unknown instance '{inst}'")
        return self

    def requires_agent(self) -> bool:
        """Return True if any instance needs XDR agent."""
        return any(i.xdr_agent for i in self.instances)

    def get_agent_requirements(self) -> dict:
        """Determine agent requirements for this scenario.

        Returns:
            {
                "requires_windows": bool,
                "requires_linux": bool,
                "has_from_agent": bool,  # Needs OS selection
            }
        """
        result = {
            "requires_windows": False,
            "requires_linux": False,
            "has_from_agent": False,
        }
        for inst in self.instances:
            if inst.xdr_agent:
                if inst.os_type == "from_agent":
                    result["has_from_agent"] = True
                elif inst.os_type == "windows":
                    result["requires_windows"] = True
                elif inst.os_type in ("ubuntu", "kali"):
                    result["requires_linux"] = True
        return result
