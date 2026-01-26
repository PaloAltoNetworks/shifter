"""Behaviour DSL schemas for CMS data contracts.

These Pydantic models define the Behaviour DSL - a layered schema system where:
- Specs (BehaviourSpec, etc.) are type-specific creation schemas
- Projections (BehaviourContext, BehaviourRef) provide tailored views for specific use cases

Behaviours are specifications of actor activity within cyber ranges. They define
what an actor (attacker, defender, simulated user) does, including:
- Objectives: What the behavior aims to achieve
- Steps: Ordered sequence of actions
- Context requirements: What capabilities/access the behavior needs

Behaviour types:
- attack: Offensive behaviors (future specialization)
- defender: Defensive behaviors (future specialization)
- simulated_user: Normal user activity simulation (future specialization)

Future considerations:
- Achievability checking: Can objectives be met given range constraints?
- Behavior composition: Multiple behaviors executing in the same range
- Actor binding: Linking behaviors to specific instances
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Discriminator, field_validator, model_validator

from .base import SpecBase
from .objective import ObjectiveContext, ObjectivePriority, ObjectiveSpec, ObjectiveStatus
from .step import FailureAction, StepContext, StepSpec, StepStatus

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class BehaviourStatus(str, Enum):
    """Behaviour execution status.

    DRAFT: Behavior is being defined, not ready for execution.
    READY: Behavior is complete and ready for execution.
    RUNNING: Behavior is currently executing.
    PAUSED: Behavior execution is paused.
    COMPLETED: Behavior finished executing (check objectives for success).
    FAILED: Behavior failed to execute.
    CANCELLED: Behavior was cancelled before completion.
    """

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CapabilityType(str, Enum):
    """Types of capabilities a behavior may require.

    These represent what access/abilities a behavior needs from its
    execution context (the instance/range it runs on).
    """

    SHELL_ACCESS = "shell_access"
    ROOT_ACCESS = "root_access"
    NETWORK_ACCESS = "network_access"
    FILE_SYSTEM_ACCESS = "file_system_access"
    PROCESS_CONTROL = "process_control"
    USER_CONTEXT = "user_context"
    GUI_ACCESS = "gui_access"
    ADMIN_ACCESS = "admin_access"


# =============================================================================
# Behaviour Specs - type-specific creation schemas
# =============================================================================


class BehaviourSpecBase(SpecBase):
    """Base specification for all behaviour types.

    Extends SpecBase with fields common to all behaviours. This is the
    foundation for specialized behavior types (attack, defender, simulated_user).

    Attributes:
        name: User-friendly behaviour name (inherited from SpecBase).
        description: Human-readable description of the behavior.
        objectives: List of objectives this behavior aims to achieve.
        steps: Ordered list of steps that implement the behavior.
        required_capabilities: Capabilities the behavior needs to execute.
        target_os_types: OS types this behavior can run on.
        tags: Optional tags for categorization (e.g., "MITRE:T1059").
        version: Version of the behavior specification.
    """

    description: str | None = None
    objectives: list[ObjectiveSpec] = []
    steps: list[StepSpec] = []
    required_capabilities: list[CapabilityType] = []
    target_os_types: list[Literal["windows", "linux", "kali", "ubuntu", "panos"]] = []
    tags: list[str] = []
    version: str = "1.0.0"

    @field_validator("tags")
    @classmethod
    def tags_not_empty_strings(cls, v: list[str]) -> list[str]:
        """Validate tags don't contain empty strings."""
        for i, tag in enumerate(v):
            if not tag or not tag.strip():
                raise ValueError(f"Tag at index {i} cannot be empty or whitespace")
        return [t.strip() for t in v]

    @field_validator("version")
    @classmethod
    def version_not_empty(cls, v: str) -> str:
        """Validate version is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("version cannot be empty or whitespace")
        return v.strip()

    @model_validator(mode="after")
    def validate_step_ordering(self) -> BehaviourSpecBase:
        """Validate that step orders are unique and sequential."""
        if not self.steps:
            return self

        orders = [step.order for step in self.steps]
        if len(orders) != len(set(orders)):
            raise ValueError("Step orders must be unique")

        return self

    @model_validator(mode="after")
    def validate_step_dependencies(self) -> BehaviourSpecBase:
        """Validate that step dependencies reference existing steps."""
        if not self.steps:
            return self

        step_names = {step.name for step in self.steps if step.name}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_names:
                    raise ValueError(
                        f"Step '{step.name}' depends on unknown step '{dep}'"
                    )
        return self

    @property
    def sorted_steps(self) -> list[StepSpec]:
        """Return steps sorted by execution order."""
        return sorted(self.steps, key=lambda s: s.order)

    @property
    def critical_objectives(self) -> list[ObjectiveSpec]:
        """Return objectives with critical priority."""
        return [o for o in self.objectives if o.priority == ObjectivePriority.CRITICAL]

    @property
    def has_verification_steps(self) -> bool:
        """Return True if behavior has any verification steps."""
        return any(step.is_verification for step in self.steps)


class AttackBehaviourSpec(BehaviourSpecBase):
    """Specification for creating an attack behaviour.

    Attack behaviors represent offensive activities that an attacker might
    perform. They typically have objectives like gaining access, exfiltrating
    data, or achieving persistence.

    This is a placeholder for future specialization. Attack-specific fields
    like MITRE ATT&CK mappings, kill chain phase, etc. will be added.

    Attributes:
        behaviour_type: Discriminator field, always 'attack'.
    """

    behaviour_type: Literal["attack"] = "attack"


class DefenderBehaviourSpec(BehaviourSpecBase):
    """Specification for creating a defender behaviour.

    Defender behaviors represent defensive activities like monitoring,
    detection, response, and remediation. They typically have objectives
    like detecting attacks, maintaining availability, or preventing breaches.

    This is a placeholder for future specialization. Defender-specific fields
    like detection rules, response playbooks, etc. will be added.

    Attributes:
        behaviour_type: Discriminator field, always 'defender'.
    """

    behaviour_type: Literal["defender"] = "defender"


class SimulatedUserBehaviourSpec(BehaviourSpecBase):
    """Specification for creating a simulated user behaviour.

    Simulated user behaviors represent normal user activity that provides
    realistic background traffic and system usage. They help distinguish
    attack activity from normal operations.

    This is a placeholder for future specialization. User simulation-specific
    fields like activity patterns, personas, etc. will be added.

    Attributes:
        behaviour_type: Discriminator field, always 'simulated_user'.
    """

    behaviour_type: Literal["simulated_user"] = "simulated_user"


# Discriminated union - Pydantic auto-routes based on behaviour_type field
BehaviourSpec = Annotated[
    AttackBehaviourSpec | DefenderBehaviourSpec | SimulatedUserBehaviourSpec,
    Discriminator("behaviour_type"),
]


# =============================================================================
# Projections - tailored views of the Behaviour DSL kernel
# =============================================================================


class BehaviourContextBase(BaseModel):
    """Base projection for all behaviour types.

    Contains fields common to all behaviour contexts.
    Type-specific contexts extend this with their own fields.

    Attributes:
        behaviour_id: Unique identifier of the behaviour.
        name: User-friendly behaviour name.
        description: Human-readable description.
        status: Current execution status.
        objectives: List of objective projections.
        steps: List of step projections.
        tags: Categorization tags.
        version: Behavior specification version.
    """

    behaviour_id: int | str
    name: str
    description: str | None = None
    status: BehaviourStatus = BehaviourStatus.READY
    objectives: list[ObjectiveContext] = []
    steps: list[StepContext] = []
    tags: list[str] = []
    version: str = "1.0.0"

    @field_validator("behaviour_id")
    @classmethod
    def behaviour_id_valid(cls, v: int | str) -> int | str:
        """Validate behaviour_id is valid."""
        if isinstance(v, int) and v <= 0:
            raise ValueError("behaviour_id must be a positive integer")
        if isinstance(v, str) and not v.strip():
            raise ValueError("behaviour_id cannot be empty or whitespace")
        return v

    @property
    def objective_count(self) -> int:
        """Return number of objectives."""
        return len(self.objectives)

    @property
    def step_count(self) -> int:
        """Return number of steps."""
        return len(self.steps)

    @property
    def is_running(self) -> bool:
        """Return True if behavior is currently running."""
        return self.status == BehaviourStatus.RUNNING

    @property
    def is_complete(self) -> bool:
        """Return True if behavior has finished (successfully or not)."""
        return self.status in (
            BehaviourStatus.COMPLETED,
            BehaviourStatus.FAILED,
            BehaviourStatus.CANCELLED,
        )


class AttackBehaviourContext(BehaviourContextBase):
    """Attack behaviour projection for templates.

    Attributes:
        behaviour_type: Discriminator field, always 'attack'.
    """

    behaviour_type: Literal["attack"] = "attack"


class DefenderBehaviourContext(BehaviourContextBase):
    """Defender behaviour projection for templates.

    Attributes:
        behaviour_type: Discriminator field, always 'defender'.
    """

    behaviour_type: Literal["defender"] = "defender"


class SimulatedUserBehaviourContext(BehaviourContextBase):
    """Simulated user behaviour projection for templates.

    Attributes:
        behaviour_type: Discriminator field, always 'simulated_user'.
    """

    behaviour_type: Literal["simulated_user"] = "simulated_user"


# Discriminated union - Pydantic auto-routes based on behaviour_type field
BehaviourContext = Annotated[
    AttackBehaviourContext | DefenderBehaviourContext | SimulatedUserBehaviourContext,
    Discriminator("behaviour_type"),
]


class BehaviourRef(BaseModel):
    """Minimal behaviour reference for operations.

    Contains only the identifiers needed to reference a behaviour.
    Used for delete operations and status checks.

    Attributes:
        behaviour_id: Unique identifier of the behaviour.
        behaviour_type: Type of behaviour.
        status: Current status.
    """

    behaviour_id: int | str
    behaviour_type: Literal["attack", "defender", "simulated_user"]
    status: BehaviourStatus = BehaviourStatus.READY

    @field_validator("behaviour_id")
    @classmethod
    def behaviour_id_valid(cls, v: int | str) -> int | str:
        """Validate behaviour_id is valid."""
        if isinstance(v, int) and v <= 0:
            raise ValueError("behaviour_id must be a positive integer")
        if isinstance(v, str) and not v.strip():
            raise ValueError("behaviour_id cannot be empty or whitespace")
        return v


class BehaviourResult(BaseModel):
    """Result of behaviour execution.

    Captures the outcome of executing a behavior, including status,
    objective outcomes, and timing information.

    Attributes:
        behaviour_id: ID of the behavior that was executed.
        status: Final execution status.
        objectives_achieved: Count of objectives achieved.
        objectives_failed: Count of objectives failed.
        steps_completed: Count of steps completed.
        steps_failed: Count of steps that failed.
        duration_seconds: Total execution time.
        error: Error message if behavior failed.
    """

    behaviour_id: int | str
    status: BehaviourStatus
    objectives_achieved: int = 0
    objectives_failed: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    duration_seconds: float = 0.0
    error: str | None = None

    @field_validator("behaviour_id")
    @classmethod
    def behaviour_id_valid(cls, v: int | str) -> int | str:
        """Validate behaviour_id is valid."""
        if isinstance(v, int) and v <= 0:
            raise ValueError("behaviour_id must be a positive integer")
        if isinstance(v, str) and not v.strip():
            raise ValueError("behaviour_id cannot be empty or whitespace")
        return v

    @field_validator("objectives_achieved", "objectives_failed", "steps_completed", "steps_failed")
    @classmethod
    def counts_non_negative(cls, v: int) -> int:
        """Validate counts are non-negative."""
        if v < 0:
            raise ValueError("Count must be non-negative")
        return v

    @field_validator("duration_seconds")
    @classmethod
    def duration_non_negative(cls, v: float) -> float:
        """Validate duration is non-negative."""
        if v < 0:
            raise ValueError("duration_seconds must be non-negative")
        return v

    @property
    def success_rate(self) -> float:
        """Calculate objective success rate."""
        total = self.objectives_achieved + self.objectives_failed
        if total == 0:
            return 0.0
        return self.objectives_achieved / total

    @property
    def is_successful(self) -> bool:
        """Return True if behavior completed with all objectives achieved."""
        return (
            self.status == BehaviourStatus.COMPLETED
            and self.objectives_failed == 0
        )
