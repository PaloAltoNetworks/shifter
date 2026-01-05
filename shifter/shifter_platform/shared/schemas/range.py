"""Range DSL schemas for CMS to Engine communication.

These Pydantic models define the Range DSL - a layered schema system where:
- RangeSpec is the kernel (canonical representation of what a range IS)
- Projections (RangeContext, RangeRef) provide tailored views for specific use cases

CMS hydrates scenario templates into these schemas, and Engine validates
incoming requests against them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, computed_field, field_validator

from shared.enums import RangeStatus


class AgentDetails(BaseModel):
    """Agent file details for instance provisioning.

    Attributes:
        s3_key: S3 object key where the agent installer is stored.
        filename: Original filename of the agent installer.
        sha256: SHA256 hash of the agent file (optional, for future use).
    """

    s3_key: str
    filename: str
    sha256: str = ""


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
        uuid: Unique identifier for this instance (assigned during hydration).
        role: Instance role (attacker, victim, or dc).
        os_type: Operating system type (kali, ubuntu, or windows).
        agent: Optional agent details for agent installation.
        dc_config: Optional domain controller configuration.
        join_domain: Whether instance should join the domain (default False).
    """

    uuid: str | None = None
    role: Literal["attacker", "victim", "dc"]
    os_type: Literal["kali", "ubuntu", "windows"]
    agent: AgentDetails | None = None
    dc_config: DCConfig | None = None
    join_domain: bool = False


class RangeSpec(BaseModel):
    """Complete specification of a cyber range.

    This is the kernel of the Range DSL - the canonical representation of what
    a range IS. Used for creation requests from CMS to Engine, and as the base
    for projections (views) tailored to specific use cases.

    Attributes:
        scenario_id: Identifier of the scenario being deployed.
        user_id: ID of the user who owns this range.
        instances: List of instance specifications for the range.
    """

    scenario_id: str
    user_id: int
    instances: list[InstanceSpec]

    @field_validator("scenario_id")
    @classmethod
    def scenario_id_not_empty(cls, v: str) -> str:
        """Validate scenario_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("scenario_id cannot be empty or whitespace")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


# =============================================================================
# Projections - tailored views of the Range DSL kernel
# =============================================================================


class InstanceContext(BaseModel):
    """Template-safe projection of an instance.

    Excludes agent secrets, keeps only display-relevant fields.
    Used by Mission Control for rendering templates.

    Attributes:
        uuid: Unique identifier for this instance.
        role: Instance role (attacker, victim, or dc).
        os_type: Operating system type (kali, ubuntu, or windows).
        join_domain: Whether instance should join the domain.
    """

    uuid: str | None = None
    role: Literal["attacker", "victim", "dc"]
    os_type: Literal["kali", "ubuntu", "windows"]
    join_domain: bool = False


class RangeContext(BaseModel):
    """Template-safe projection of a range.

    Used by Mission Control for rendering templates. Excludes:
    - Agent secrets (s3_key, sha256)
    - Internal IDs that shouldn't be exposed to frontend

    Attributes:
        range_id: Unique identifier of the range.
        scenario_id: Identifier of the scenario being deployed.
        user_id: ID of the user who owns this range.
        status: Current status of the range.
        instances: List of template-safe instance projections.
        agent_name: Display name of the agent used (optional).

    Computed Properties:
        is_ready: True if range is ready for use.
        is_terminal: True if range is in a terminal state (destroyed/failed).
        is_active: True if range is not in a terminal state.
    """

    range_id: int
    scenario_id: str
    user_id: int
    status: RangeStatus
    instances: list[InstanceContext]
    agent_name: str | None = None

    @field_validator("range_id")
    @classmethod
    def range_id_positive(cls, v: int) -> int:
        """Validate range_id is a positive integer."""
        if v <= 0:
            raise ValueError("range_id must be a positive integer")
        return v

    @field_validator("scenario_id")
    @classmethod
    def scenario_id_not_empty(cls, v: str) -> str:
        """Validate scenario_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("scenario_id cannot be empty or whitespace")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v

    @computed_field
    @property
    def is_ready(self) -> bool:
        """True if range is ready for use (terminal available)."""
        return self.status == RangeStatus.READY

    @computed_field
    @property
    def is_terminal(self) -> bool:
        """True if range is in a terminal state (destroyed or failed)."""
        return self.status in (RangeStatus.DESTROYED, RangeStatus.FAILED)

    @computed_field
    @property
    def is_active(self) -> bool:
        """True if range is not in a terminal state."""
        return not self.is_terminal


class RangeRef(BaseModel):
    """Minimal range reference for operations like destroy/cancel.

    Contains only the identifiers needed to reference a range.
    Used for status updates and lifecycle operations.

    Attributes:
        range_id: Unique identifier of the range.
        user_id: ID of the user who owns this range.
        status: Current status of the range.
    """

    range_id: int
    user_id: int
    status: RangeStatus

    @field_validator("range_id")
    @classmethod
    def range_id_positive(cls, v: int) -> int:
        """Validate range_id is a positive integer."""
        if v <= 0:
            raise ValueError("range_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v
