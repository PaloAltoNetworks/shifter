"""Step DSL schemas for behavior specifications.

These Pydantic models define the Step DSL - sequenced actions within a behavior.
Steps bind actions to execution order and define failure handling.

Steps provide the procedural structure for behaviors, allowing actions to be
sequenced, conditionally executed, and composed into complex workflows.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, field_validator, model_validator

from .base import SpecBase

if TYPE_CHECKING:
    from .action import ActionSpec

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class FailureAction(str, Enum):
    """How to handle step execution failure.

    ABORT: Stop behavior execution immediately (default).
    CONTINUE: Log failure and proceed to next step.
    RETRY: Retry the step up to max_retries times.
    SKIP: Skip this step and continue (for optional steps).
    """

    ABORT = "abort"
    CONTINUE = "continue"
    RETRY = "retry"
    SKIP = "skip"


class StepStatus(str, Enum):
    """Step execution status.

    Used for tracking step execution state during behavior execution.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


# =============================================================================
# Step Specs
# =============================================================================


class StepSpec(SpecBase):
    """Specification for a step in a behavior sequence.

    A step binds an action to an execution order within a behavior.
    Steps define when and how actions are executed, including conditional
    execution, failure handling, and retry logic.

    Attributes:
        name: User-friendly step name (inherited from SpecBase).
        description: Human-readable description of this step's purpose.
        action: The action to execute in this step.
        order: Execution order (0-indexed, lower executes first).
        condition: Optional condition for step execution.
            If provided, step only executes if condition is true.
        timeout_seconds: Maximum time for step execution.
        on_failure: How to handle execution failure.
        max_retries: Maximum retry attempts (when on_failure is RETRY).
        retry_delay_seconds: Delay between retry attempts.
        is_verification: If True, this step verifies state rather than changing it.
        depends_on: List of step names that must complete before this step.
    """

    description: str | None = None
    action: ActionSpec
    order: int = 0
    condition: str | None = None
    timeout_seconds: int = 300
    on_failure: FailureAction = FailureAction.ABORT
    max_retries: int = 3
    retry_delay_seconds: int = 5
    is_verification: bool = False
    depends_on: list[str] = []

    @field_validator("order")
    @classmethod
    def order_non_negative(cls, v: int) -> int:
        """Validate order is non-negative."""
        if v < 0:
            raise ValueError("order must be non-negative")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        """Validate timeout is a positive integer."""
        if v <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        return v

    @field_validator("max_retries")
    @classmethod
    def max_retries_non_negative(cls, v: int) -> int:
        """Validate max_retries is non-negative."""
        if v < 0:
            raise ValueError("max_retries must be non-negative")
        return v

    @field_validator("retry_delay_seconds")
    @classmethod
    def retry_delay_non_negative(cls, v: int) -> int:
        """Validate retry_delay_seconds is non-negative."""
        if v < 0:
            raise ValueError("retry_delay_seconds must be non-negative")
        return v

    @field_validator("depends_on")
    @classmethod
    def depends_on_no_empty_strings(cls, v: list[str]) -> list[str]:
        """Validate depends_on doesn't contain empty strings."""
        for i, dep in enumerate(v):
            if not dep or not dep.strip():
                raise ValueError(f"Dependency at index {i} cannot be empty or whitespace")
        return [d.strip() for d in v]

    @model_validator(mode="after")
    def validate_retry_config(self) -> StepSpec:
        """Validate retry configuration is consistent."""
        if self.on_failure == FailureAction.RETRY and self.max_retries == 0:
            raise ValueError("max_retries must be > 0 when on_failure is RETRY")
        return self


# =============================================================================
# Projections
# =============================================================================


class StepContext(BaseModel):
    """Step projection for display.

    Contains fields needed for step display in UI contexts.
    Excludes sensitive action details.

    Attributes:
        step_id: Unique identifier for this step.
        name: User-friendly step name.
        description: Human-readable description.
        order: Execution order.
        action_type: Type of action in this step.
        is_verification: Whether this is a verification step.
        status: Current execution status (for running behaviors).
    """

    step_id: str
    name: str | None = None
    description: str | None = None
    order: int
    action_type: str
    is_verification: bool = False
    status: StepStatus = StepStatus.PENDING

    @field_validator("step_id")
    @classmethod
    def step_id_not_empty(cls, v: str) -> str:
        """Validate step_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("step_id cannot be empty or whitespace")
        return v.strip()

    @field_validator("order")
    @classmethod
    def order_non_negative(cls, v: int) -> int:
        """Validate order is non-negative."""
        if v < 0:
            raise ValueError("order must be non-negative")
        return v


class StepRef(BaseModel):
    """Minimal step reference for operations.

    Contains only the identifiers needed to reference a step.
    Used for dependency declaration and step lookup.

    Attributes:
        step_id: Unique identifier of the step.
        name: Step name (for human-readable references).
    """

    step_id: str
    name: str | None = None

    @field_validator("step_id")
    @classmethod
    def step_id_not_empty(cls, v: str) -> str:
        """Validate step_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("step_id cannot be empty or whitespace")
        return v.strip()


class StepResult(BaseModel):
    """Result of step execution.

    Captures the outcome of executing a step, including success/failure,
    output, and timing information.

    Attributes:
        step_id: ID of the step that was executed.
        status: Final execution status.
        output: Output from step execution.
        error: Error message if step failed.
        duration_seconds: How long the step took.
        retries_used: Number of retry attempts made.
    """

    step_id: str
    status: StepStatus
    output: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    retries_used: int = 0

    @field_validator("step_id")
    @classmethod
    def step_id_not_empty(cls, v: str) -> str:
        """Validate step_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("step_id cannot be empty or whitespace")
        return v.strip()

    @field_validator("duration_seconds")
    @classmethod
    def duration_non_negative(cls, v: float) -> float:
        """Validate duration is non-negative."""
        if v < 0:
            raise ValueError("duration_seconds must be non-negative")
        return v

    @field_validator("retries_used")
    @classmethod
    def retries_non_negative(cls, v: int) -> int:
        """Validate retries_used is non-negative."""
        if v < 0:
            raise ValueError("retries_used must be non-negative")
        return v
