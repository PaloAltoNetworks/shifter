"""Objective DSL schemas for behavior specifications.

These Pydantic models define the Objective DSL - goals that behaviors aim to
achieve. Objectives provide the foundation for future achievability checking.

Objective types:
- achieve: A condition that must become true
- maintain: A condition that must remain true throughout
- prevent: A condition that must not become true

Objectives enable future analysis of whether attacker goals can be reached,
defender goals can be maintained, and whether scenarios are well-formed.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator

from .base import SpecBase

if TYPE_CHECKING:
    from .step import StepSpec

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class ObjectiveType(str, Enum):
    """Type of objective.

    ACHIEVE: A condition that must become true at some point.
        Example: "gain_shell_access", "exfiltrate_data"

    MAINTAIN: A condition that must remain true throughout execution.
        Example: "maintain_stealth", "preserve_availability"

    PREVENT: A condition that must not become true.
        Example: "prevent_data_loss", "prevent_privilege_escalation"
    """

    ACHIEVE = "achieve"
    MAINTAIN = "maintain"
    PREVENT = "prevent"


class ObjectiveStatus(str, Enum):
    """Status of an objective during behavior execution.

    PENDING: Objective not yet evaluated.
    IN_PROGRESS: Working toward objective.
    ACHIEVED: Objective condition is met.
    MAINTAINED: Maintain objective is still valid.
    VIOLATED: Maintain or prevent objective was violated.
    FAILED: Could not achieve objective.
    NOT_APPLICABLE: Objective was skipped or not relevant.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    ACHIEVED = "achieved"
    MAINTAINED = "maintained"
    VIOLATED = "violated"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class ObjectivePriority(str, Enum):
    """Priority of an objective.

    CRITICAL: Must be met for behavior to succeed.
    HIGH: Should be met, failure is significant.
    MEDIUM: Desired but not required.
    LOW: Nice to have, informational.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# =============================================================================
# Objective Specs
# =============================================================================


class ObjectiveSpec(SpecBase):
    """Specification for a behavior objective.

    An objective defines a goal that a behavior aims to achieve, maintain,
    or prevent. Objectives are used for:
    1. Documenting behavior intent
    2. Future achievability checking
    3. Success/failure evaluation

    Attributes:
        name: User-friendly objective name (inherited from SpecBase).
        description: Human-readable description of the objective.
        objective_type: The type of objective (achieve/maintain/prevent).
        priority: Importance of this objective.
        success_condition: Condition string that defines objective success.
            Uses string-based conditions for future parsing/evaluation.
        verification_steps: Optional list of step names that verify this objective.
        depends_on: Other objectives that must be met first.
        tags: Optional tags for categorization (e.g., "MITRE:T1059").
    """

    description: str
    objective_type: ObjectiveType = ObjectiveType.ACHIEVE
    priority: ObjectivePriority = ObjectivePriority.HIGH
    success_condition: str | None = None
    verification_steps: list[str] = []
    depends_on: list[str] = []
    tags: list[str] = []

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        """Validate description is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("description cannot be empty or whitespace")
        return v.strip()

    @field_validator("verification_steps", "depends_on", "tags")
    @classmethod
    def list_items_not_empty(cls, v: list[str]) -> list[str]:
        """Validate list items are not empty strings."""
        for i, item in enumerate(v):
            if not item or not item.strip():
                raise ValueError(f"Item at index {i} cannot be empty or whitespace")
        return [item.strip() for item in v]


# =============================================================================
# Projections
# =============================================================================


class ObjectiveContext(BaseModel):
    """Objective projection for display.

    Contains fields needed for objective display in UI contexts.

    Attributes:
        objective_id: Unique identifier for this objective.
        name: User-friendly objective name.
        description: Human-readable description.
        objective_type: The type of objective.
        priority: Importance of this objective.
        status: Current status (for running behaviors).
        tags: Categorization tags.
    """

    objective_id: str
    name: str | None = None
    description: str
    objective_type: ObjectiveType
    priority: ObjectivePriority = ObjectivePriority.HIGH
    status: ObjectiveStatus = ObjectiveStatus.PENDING
    tags: list[str] = []

    @field_validator("objective_id")
    @classmethod
    def objective_id_not_empty(cls, v: str) -> str:
        """Validate objective_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("objective_id cannot be empty or whitespace")
        return v.strip()

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        """Validate description is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("description cannot be empty or whitespace")
        return v.strip()


class ObjectiveRef(BaseModel):
    """Minimal objective reference for operations.

    Contains only the identifiers needed to reference an objective.
    Used for dependency declaration and objective lookup.

    Attributes:
        objective_id: Unique identifier of the objective.
        name: Objective name (for human-readable references).
        objective_type: Type of objective.
    """

    objective_id: str
    name: str | None = None
    objective_type: ObjectiveType

    @field_validator("objective_id")
    @classmethod
    def objective_id_not_empty(cls, v: str) -> str:
        """Validate objective_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("objective_id cannot be empty or whitespace")
        return v.strip()


class ObjectiveResult(BaseModel):
    """Result of objective evaluation.

    Captures the outcome of evaluating an objective after behavior execution.

    Attributes:
        objective_id: ID of the objective that was evaluated.
        status: Final objective status.
        achieved_at_step: Name of step where objective was achieved (if any).
        violated_at_step: Name of step where objective was violated (if any).
        evaluation_notes: Human-readable notes about the evaluation.
    """

    objective_id: str
    status: ObjectiveStatus
    achieved_at_step: str | None = None
    violated_at_step: str | None = None
    evaluation_notes: str | None = None

    @field_validator("objective_id")
    @classmethod
    def objective_id_not_empty(cls, v: str) -> str:
        """Validate objective_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("objective_id cannot be empty or whitespace")
        return v.strip()
