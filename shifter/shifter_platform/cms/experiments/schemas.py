"""Pydantic schemas for experiment validation.

These schemas validate user input before it reaches the database layer.
"""

from __future__ import annotations

from enum import StrEnum

from cyberscript.template_vars import TemplateString
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExperimentStatus(StrEnum):
    """Experiment lifecycle states."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class RunStatus(StrEnum):
    """Experiment run lifecycle states."""

    PENDING = "pending"
    PROVISIONING = "provisioning"
    EXECUTING_VICTIMS = "executing_victims"
    EXECUTING_ATTACKER = "executing_attacker"
    COLLECTING = "collecting"
    COMPLETED = "completed"
    FAILED = "failed"


class ScriptType(StrEnum):
    """Types of scripts that can be assigned to instances."""

    PYTHON = "python"
    CLAUDE_CODE = "claude_code"


class ArtifactType(StrEnum):
    """Types of collected artifacts."""

    SCRIPT_OUTPUT = "script_output"
    CLAUDE_TRANSCRIPT = "claude_transcript"


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

EXPERIMENT_TRANSITIONS: dict[ExperimentStatus, set[ExperimentStatus]] = {
    ExperimentStatus.DRAFT: {ExperimentStatus.QUEUED},
    ExperimentStatus.QUEUED: {ExperimentStatus.RUNNING, ExperimentStatus.CANCELLED, ExperimentStatus.FAILED},
    ExperimentStatus.RUNNING: {
        ExperimentStatus.COMPLETED,
        ExperimentStatus.CANCELLED,
        ExperimentStatus.FAILED,
    },
    ExperimentStatus.COMPLETED: set(),
    ExperimentStatus.CANCELLED: set(),
    ExperimentStatus.FAILED: set(),
}

RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.PROVISIONING, RunStatus.FAILED},
    RunStatus.PROVISIONING: {RunStatus.EXECUTING_VICTIMS, RunStatus.FAILED},
    RunStatus.EXECUTING_VICTIMS: {RunStatus.EXECUTING_ATTACKER, RunStatus.FAILED},
    RunStatus.EXECUTING_ATTACKER: {RunStatus.COLLECTING, RunStatus.FAILED},
    RunStatus.COLLECTING: {RunStatus.COMPLETED, RunStatus.FAILED},
    RunStatus.COMPLETED: set(),
    RunStatus.FAILED: set(),
}

TERMINAL_EXPERIMENT_STATUSES = {
    ExperimentStatus.COMPLETED,
    ExperimentStatus.CANCELLED,
    ExperimentStatus.FAILED,
}

TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
}


# ---------------------------------------------------------------------------
# Input schemas (for validating user-provided data)
# ---------------------------------------------------------------------------


class ScriptUploadInput(BaseModel):
    """Validates script upload request data."""

    name: str = Field(..., min_length=1, max_length=255)
    filename: str = Field(..., min_length=1, max_length=255)
    file_size: int = Field(..., gt=0)

    @field_validator("filename")
    @classmethod
    def filename_must_be_python(cls, v: str) -> str:
        if not v.lower().endswith(".py"):
            raise ValueError("Only .py files are allowed")
        return v

    @field_validator("file_size")
    @classmethod
    def file_size_within_limit(cls, v: int) -> int:
        max_size = 1 * 1024 * 1024  # 1MB
        if v > max_size:
            raise ValueError(f"File size {v} exceeds maximum of {max_size} bytes")
        return v


class ScriptAssignmentInput(BaseModel):
    """Validates a single script assignment within an experiment."""

    instance_name: str = Field(..., min_length=1, max_length=100)
    script_type: ScriptType
    script_id: int | None = None
    claude_prompt: TemplateString | None = None
    execution_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_script_type_data(self) -> ScriptAssignmentInput:
        if self.script_type == ScriptType.PYTHON and not self.script_id:
            raise ValueError("script_id is required for python script type")
        if self.script_type == ScriptType.CLAUDE_CODE and not self.claude_prompt:
            raise ValueError("claude_prompt is required for claude_code script type")
        return self


class ExperimentCreateInput(BaseModel):
    """Validates experiment creation request data."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    scenario_id: str = Field(..., min_length=1, max_length=100)
    agent_id: int | None = None
    total_runs: int = Field(default=1, ge=1, le=10)
    max_parallel_runs: int = Field(default=1, ge=1, le=5)
    scripts: list[ScriptAssignmentInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_parallel_vs_total(self) -> ExperimentCreateInput:
        if self.max_parallel_runs > self.total_runs:
            raise ValueError("max_parallel_runs cannot exceed total_runs")
        return self
