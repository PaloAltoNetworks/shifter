"""Range request schemas for CMS to Engine communication.

These Pydantic models define the data contract for range creation requests.
CMS hydrates scenario templates into these schemas, and Engine validates
incoming requests against them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AgentDetails(BaseModel):
    """Agent file details for instance provisioning.

    Attributes:
        s3_key: S3 object key where the agent installer is stored.
        filename: Original filename of the agent installer.
        sha256: SHA256 hash of the agent file for verification.
    """

    s3_key: str
    filename: str
    sha256: str


class DCConfig(BaseModel):
    """Domain Controller configuration.

    Attributes:
        domain_name: Full domain name (e.g., 'lab.local').
        netbios_name: NetBIOS domain name (e.g., 'LAB').
    """

    domain_name: str
    netbios_name: str


class InstanceSpec(BaseModel):
    """Single instance specification.

    Attributes:
        role: Instance role (attacker, victim, or dc).
        os_type: Operating system type (kali, ubuntu, or windows).
        agent: Optional agent details for instances that need agent installation.
        dc_config: Optional domain controller configuration.
        join_domain: Whether instance should join the domain (default False).
    """

    role: Literal["attacker", "victim", "dc"]
    os_type: Literal["kali", "ubuntu", "windows"]
    agent: AgentDetails | None = None
    dc_config: DCConfig | None = None
    join_domain: bool = False


class RangeRequest(BaseModel):
    """Complete range creation request.

    This is the data contract between CMS and Engine for creating a range.
    CMS hydrates scenario templates into this schema, and Engine validates
    incoming requests against it.

    Attributes:
        scenario_id: Identifier of the scenario being deployed.
        user_id: ID of the user requesting the range.
        instances: List of instance specifications for the range.
    """

    scenario_id: str
    user_id: int
    instances: list[InstanceSpec]
