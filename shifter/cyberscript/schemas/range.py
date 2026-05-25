"""Range DSL schemas for CMS to Engine communication.

These Pydantic models define the Range DSL - a layered schema system where:
- RangeSpec is the kernel (canonical representation of what a range IS)
- Projections (RangeContext, RangeRef) provide tailored views for specific use cases

CMS hydrates scenario templates into these schemas, and Engine validates
incoming requests against them.
"""

from __future__ import annotations

import uuid as uuid_module
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, computed_field, field_validator

from ..enums import ResourceStatus

from .base import SpecBase

if TYPE_CHECKING:
    from .app import NGFWAppSpec
    from .subnet import SubnetSpec


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
    ami_key: str | None = None
    instance_type: str | None = None
    ngfw_app: NGFWAppSpec | None = None

    @classmethod
    def from_template(
        cls,
        data: dict[str, Any],
        agents: dict[str, Any] | None = None,
    ) -> InstanceSpec:
        """Create an InstanceSpec from a scenario template dict.

        Handles:
        - UUID assignment
        - os_type resolution for "from_agent"
        - Agent lookup and AgentDetails creation for xdr_agent instances
        - DCConfig conversion

        Args:
            data: Template dict with keys: name, role, os_type, xdr_agent,
                  domain_controller, join_domain, dc_config.
            agents: Optional mapping of OS type to agent object. Agent objects
                    must have s3_key, original_filename, sha256_hash attributes.

        Returns:
            Hydrated InstanceSpec ready for Engine consumption.

        Raises:
            ValueError: If required fields are missing or agent lookup fails.
        """
        name, role, template_os_type = _extract_required_fields(data)
        agents = agents or {}

        # Resolve OS type and agent
        xdr_agent = data.get("xdr_agent", False)
        os_type, agent_obj = _resolve_os_and_agent(name, template_os_type, xdr_agent, agents)

        # Build AgentDetails if agent found
        agent_details = _build_agent_details(agent_obj) if agent_obj else None

        # Build DCConfig if present
        dc_config = _build_dc_config(data.get("dc_config"))

        return cls(
            name=name,
            uuid=str(uuid_module.uuid4()),
            role=cast(Literal["attacker", "victim", "dc", "ngfw"], role),
            os_type=cast(Literal["kali", "ubuntu", "windows", "panos"], os_type),
            agent=agent_details,
            dc_config=dc_config,
            join_domain=data.get("join_domain", False),
            ami_key=data.get("ami_key"),
            instance_type=data.get("instance_type"),
        )


def _extract_required_fields(data: dict[str, Any]) -> tuple[str, str, str]:
    """Extract and validate required template fields."""
    name = data.get("name")
    role = data.get("role")
    os_type = data.get("os_type")

    if not name:
        raise ValueError("Instance template requires 'name' field")
    if not role:
        raise ValueError("Instance template requires 'role' field")
    if not os_type:
        raise ValueError("Instance template requires 'os_type' field")

    return name, role, os_type


def _resolve_os_and_agent(
    name: str,
    template_os_type: str,
    xdr_agent: bool,
    agents: dict[str, Any],
) -> tuple[str, Any]:
    """Resolve OS type and find matching agent.

    Returns:
        Tuple of (resolved_os_type, agent_object or None).
    """
    if not xdr_agent:
        return template_os_type, None

    if template_os_type == "from_agent":
        agent_obj = next(iter(agents.values()), None)
        if agent_obj is None:
            raise ValueError(f"Instance '{name}' uses from_agent but no agent provided")
        return _resolve_agent_os(agent_obj), agent_obj

    if template_os_type == "windows":
        return template_os_type, agents.get("windows")

    if template_os_type in ("ubuntu", "kali"):
        return template_os_type, agents.get("linux")

    return template_os_type, None


def _resolve_agent_os(agent: Any) -> str:
    """Map agent OS to provisioner os_type."""
    os_slug = agent.os.slug.lower()
    return "windows" if os_slug == "windows" else "ubuntu"


def _build_agent_details(agent_obj: Any) -> AgentDetails:
    """Build AgentDetails from agent object."""
    return AgentDetails(
        s3_key=agent_obj.s3_key,
        filename=agent_obj.original_filename,
        sha256=agent_obj.sha256_hash or "",
    )


def _build_dc_config(dc_config_data: dict[str, Any] | None) -> DCConfig | None:
    """Build DCConfig from template data."""
    if not dc_config_data:
        return None
    return DCConfig(
        domain_name=dc_config_data["domain_name"],
        netbios_name=dc_config_data["netbios_name"],
    )


class RangeSpecBase(SpecBase):
    """Base specification for all range types.

    Extends SpecBase with fields common to all ranges.

    Attributes:
        name: Optional range name (inherited from SpecBase).
        scenario_id: Identifier of the scenario being deployed.
        user_id: ID of the user who owns this range.
        subnets: List of subnet specifications containing instances.
    """

    scenario_id: str
    user_id: int
    subnets: list[SubnetSpec]

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

    @property
    def all_instances(self) -> list[InstanceSpec]:
        """Return flattened list of all instances across all subnets."""
        return [inst for subnet in self.subnets for inst in subnet.instances]


class RangeSpec(RangeSpecBase):
    """Demo range specification.

    Currently the only range type. Future types (ctf, training, etc.)
    will extend RangeSpecBase with their own discriminator values.

    Attributes:
        range_type: Discriminator field, always 'demo'.
        ngfw: Whether this range requires NGFW traffic inspection.
    """

    range_type: Literal["demo"] = "demo"
    ngfw: bool = False


# =============================================================================
# Projections - tailored views of the Range DSL kernel
# =============================================================================


_PRIVATE_IP_MAX_LEN = 64
_PRIVATE_IP_ALLOWED_CHARS = frozenset("0123456789abcdefABCDEF.:")


class InstanceContextBase(BaseModel):
    """Base projection for all instance types.

    Contains fields common to all instance contexts.
    Type-specific contexts extend this with their own fields.

    Attributes:
        uuid: Unique identifier for this instance.
        name: User-friendly display name for this instance.
        role: Instance role (attacker, victim, dc, or ngfw).
        os_type: Operating system type (kali, ubuntu, windows, or panos).
        join_domain: Whether instance should join the domain.
        private_ip: Optional display-only internal IP address sourced from
            engine runtime state. Malformed or oversized input is coerced to
            None rather than raised so one bad provisioner row never breaks
            the whole projection.
    """

    uuid: str | None = None
    name: str = ""
    role: Literal["attacker", "victim", "dc", "ngfw"]
    os_type: Literal["kali", "ubuntu", "windows", "panos"]
    join_domain: bool = False
    ami_key: str | None = None
    private_ip: str | None = None

    @field_validator("private_ip", mode="before")
    @classmethod
    def normalize_private_ip(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return None
        stripped = v.strip()
        if not stripped:
            return None
        if len(stripped) > _PRIVATE_IP_MAX_LEN:
            return None
        if not all(ch in _PRIVATE_IP_ALLOWED_CHARS for ch in stripped):
            return None
        return stripped


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
        request_id: UUID correlation key for Request-based pattern.
        range_id: Legacy integer identifier (optional for new Request-based ranges).
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

    request_id: UUID
    range_id: int | None = None
    scenario_id: str
    user_id: int
    status: ResourceStatus
    instances: list[InstanceContext]
    agent_name: str | None = None

    @field_validator("range_id")
    @classmethod
    def range_id_positive_if_provided(cls, v: int | None) -> int | None:
        """Validate range_id is a positive integer if provided."""
        if v is not None and v <= 0:
            raise ValueError("range_id must be a positive integer if provided")
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
        request_id: UUID correlation key for Request-based pattern.
        range_id: Legacy integer identifier (optional for new Request-based ranges).
        user_id: ID of the user who owns this range.
        status: Current status of the range.
    """

    request_id: UUID
    range_id: int | None = None
    user_id: int
    status: ResourceStatus

    @field_validator("range_id")
    @classmethod
    def range_id_positive_if_provided(cls, v: int | None) -> int | None:
        """Validate range_id is a positive integer if provided."""
        if v is not None and v <= 0:
            raise ValueError("range_id must be a positive integer if provided")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


# NOTE: Model rebuilds moved to shared/schemas/__init__.py to avoid circular imports
