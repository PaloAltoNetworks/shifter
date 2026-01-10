"""Range DSL schemas for CMS to Engine communication.

These Pydantic models define the Range DSL - a layered schema system where:
- RangeSpec is the kernel (canonical representation of what a range IS)
- Projections (RangeContext, RangeRef) provide tailored views for specific use cases

CMS hydrates scenario templates into these schemas, and Engine validates
incoming requests against them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, computed_field, field_validator

from shared.enums import ResourceStatus

from .base import SpecBase

if TYPE_CHECKING:
    from .app import NGFWAppSpec


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


class InstanceSpec(SpecBase):
    """Single instance specification.

    Supports both Range instances (attacker, victim, dc) and NGFW instances.
    For NGFW instances, the ngfw_app field contains the hydrated NGFW spec.

    Attributes:
        name: User-friendly instance name (inherited from SpecBase).
        uuid: Unique identifier for this instance (assigned during hydration).
        role: Instance role (attacker, victim, dc, or ngfw).
        os_type: Operating system type (kali, ubuntu, windows, or panos).
        agent: Optional agent details for agent installation.
        dc_config: Optional domain controller configuration.
        join_domain: Whether instance should join the domain (default False).
        ngfw_app: Optional NGFW app spec for NGFW instances.

    TODO: Remove redundant uuid field - now inherited from SpecBase (#522).
    """

    uuid: str | None = None  # TODO: Remove - inherited from SpecBase (#522)
    role: Literal["attacker", "victim", "dc", "ngfw"]
    os_type: Literal["kali", "ubuntu", "windows", "panos"]
    agent: AgentDetails | None = None
    dc_config: DCConfig | None = None
    join_domain: bool = False
    ngfw_app: NGFWAppSpec | None = None


class RangeSpecBase(SpecBase):
    """Base specification for all range types.

    Extends SpecBase with fields common to all ranges.

    Attributes:
        name: Optional range name (inherited from SpecBase).
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


class RangeSpec(RangeSpecBase):
    """Demo range specification.

    Currently the only range type. Future types (ctf, training, etc.)
    will extend RangeSpecBase with their own discriminator values.

    Attributes:
        range_type: Discriminator field, always 'demo'.
    """

    range_type: Literal["demo"] = "demo"


# =============================================================================
# Projections - tailored views of the Range DSL kernel
# =============================================================================


class InstanceContextBase(BaseModel):
    """Base projection for all instance types.

    Contains fields common to all instance contexts.
    Type-specific contexts extend this with their own fields.

    Attributes:
        uuid: Unique identifier for this instance.
        role: Instance role (attacker, victim, dc, or ngfw).
        os_type: Operating system type (kali, ubuntu, windows, or panos).
        join_domain: Whether instance should join the domain.
    """

    uuid: str | None = None
    role: Literal["attacker", "victim", "dc", "ngfw"]
    os_type: Literal["kali", "ubuntu", "windows", "panos"]
    join_domain: bool = False


class InstanceContext(InstanceContextBase):
    """Template-safe projection of an instance.

    Inherits from InstanceContextBase. Excludes agent secrets,
    keeps only display-relevant fields.
    Used by Mission Control for rendering templates.
    """

    pass


class InstanceRef(BaseModel):
    """Minimal instance reference for operations.

    Stub - not yet implemented. Instances are currently accessed via parent Range.
    """

    pass


class RangeContextBase(BaseModel):
    """Base projection for all range types.

    Contains fields common to all range contexts.
    Type-specific contexts extend this with their own fields.

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
    status: ResourceStatus
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_ready(self) -> bool:
        """True if range is ready for use (terminal available)."""
        return self.status == ResourceStatus.READY

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_terminal(self) -> bool:
        """True if range is in a terminal state (destroyed or failed)."""
        return self.status in (ResourceStatus.DESTROYED, ResourceStatus.FAILED)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_active(self) -> bool:
        """True if range is not in a terminal state."""
        return not self.is_terminal


class RangeContext(RangeContextBase):
    """Demo range projection for templates.

    Inherits from RangeContextBase. Excludes agent secrets (s3_key, sha256).
    Used by Mission Control for rendering templates.

    Attributes:
        range_type: Discriminator field, always 'demo'.
    """

    range_type: Literal["demo"] = "demo"


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
    status: ResourceStatus

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


# Rebuild InstanceSpec to resolve forward reference to NGFWAppSpec
# This must be done after NGFWAppSpec is importable
def _rebuild_instance_spec() -> None:
    """Rebuild InstanceSpec model to resolve NGFWAppSpec forward reference."""
    from .app import NGFWAppSpec  # noqa: F401

    InstanceSpec.model_rebuild()


_rebuild_instance_spec()
