"""Action DSL schemas for behavior specifications.

These Pydantic models define the Action DSL - atomic operations that can be
performed within a behavior. Actions are the building blocks of steps.

Action types: generic (extensible base for future specialization).

Future specialized types may include: command, file, network, process, etc.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Discriminator, field_validator

from .base import SpecBase

logger = logging.getLogger(__name__)

# =============================================================================
# Action Specs - type-specific creation schemas
# =============================================================================


class ActionSpecBase(SpecBase):
    """Base specification for all action types.

    Actions are atomic operations within behaviors. Each action type defines
    what operation is performed, with optional preconditions (what must be true
    before the action) and effects (what becomes true after the action).

    Preconditions and effects use string-based conditions to support future
    achievability checking without requiring schema changes.

    Attributes:
        name: User-friendly action name (inherited from SpecBase, optional).
        description: Human-readable description of what this action does.
        preconditions: List of conditions that must be true before execution.
            These are string-based to allow future parsing/evaluation.
        effects: List of state changes produced by this action.
            These are string-based to allow future matching against objectives.
    """

    description: str | None = None
    preconditions: list[str] = []
    effects: list[str] = []

    @field_validator("preconditions", "effects")
    @classmethod
    def conditions_not_empty_strings(cls, v: list[str]) -> list[str]:
        """Validate that condition lists don't contain empty strings."""
        for i, condition in enumerate(v):
            if not condition or not condition.strip():
                raise ValueError(f"Condition at index {i} cannot be empty or whitespace")
        return [c.strip() for c in v]


class GenericActionSpec(ActionSpecBase):
    """Generic action for extensibility.

    Provides a freeform action type that can represent any operation.
    Use this for actions that don't fit specialized types, or when
    defining custom operations specific to a scenario.

    Attributes:
        action_type: Discriminator field, always 'generic'.
        operation: Freeform description of the operation to perform.
        parameters: Key-value parameters for the operation.
        target: Optional target specification (e.g., file path, host).
    """

    action_type: Literal["generic"] = "generic"
    operation: str
    parameters: dict[str, Any] = {}
    target: str | None = None

    @field_validator("operation")
    @classmethod
    def operation_not_empty(cls, v: str) -> str:
        """Validate operation is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("operation cannot be empty or whitespace")
        return v.strip()


class CommandActionSpec(ActionSpecBase):
    """Command execution action.

    Represents execution of a shell command or script on a target system.
    This is the most common action type for attack/defense behaviors.

    Attributes:
        action_type: Discriminator field, always 'command'.
        command: The command or script to execute.
        shell: Shell to use for execution (default: /bin/bash for Linux).
        working_directory: Directory to execute command in.
        environment: Environment variables to set.
        timeout_seconds: Maximum execution time.
    """

    action_type: Literal["command"] = "command"
    command: str
    shell: str | None = None
    working_directory: str | None = None
    environment: dict[str, str] = {}
    timeout_seconds: int = 300

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, v: str) -> str:
        """Validate command is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("command cannot be empty or whitespace")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        """Validate timeout is a positive integer."""
        if v <= 0:
            raise ValueError("timeout_seconds must be a positive integer")
        return v


class FileActionSpec(ActionSpecBase):
    """File operation action.

    Represents file system operations like read, write, copy, delete.

    Attributes:
        action_type: Discriminator field, always 'file'.
        file_operation: The operation to perform.
        path: Target file path.
        content: Content for write operations.
        destination: Destination path for copy/move operations.
    """

    action_type: Literal["file"] = "file"
    file_operation: Literal["read", "write", "append", "copy", "move", "delete", "chmod"]
    path: str
    content: str | None = None
    destination: str | None = None
    mode: str | None = None  # For chmod operations

    @field_validator("path")
    @classmethod
    def path_not_empty(cls, v: str) -> str:
        """Validate path is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("path cannot be empty or whitespace")
        return v.strip()


class NetworkActionSpec(ActionSpecBase):
    """Network operation action.

    Represents network operations like connections, scans, traffic generation.

    Attributes:
        action_type: Discriminator field, always 'network'.
        network_operation: The operation to perform.
        target_host: Target hostname or IP address.
        target_port: Target port number.
        protocol: Network protocol to use.
        payload: Optional payload data.
    """

    action_type: Literal["network"] = "network"
    network_operation: Literal["connect", "listen", "scan", "send", "receive"]
    target_host: str | None = None
    target_port: int | None = None
    protocol: Literal["tcp", "udp", "icmp", "http", "https"] = "tcp"
    payload: str | None = None

    @field_validator("target_port")
    @classmethod
    def port_in_range(cls, v: int | None) -> int | None:
        """Validate port is in valid range if provided."""
        if v is not None and (v < 1 or v > 65535):
            raise ValueError("target_port must be between 1 and 65535")
        return v


# Discriminated union - Pydantic auto-routes based on action_type field
ActionSpec = Annotated[
    GenericActionSpec | CommandActionSpec | FileActionSpec | NetworkActionSpec,
    Discriminator("action_type"),
]


# =============================================================================
# Projections - tailored views of the Action DSL kernel
# =============================================================================


class ActionContextBase(BaseModel):
    """Base projection for all action types.

    Contains fields common to all action contexts.
    Type-specific contexts extend this with their own fields.

    Attributes:
        action_id: Unique identifier of the action.
        name: User-friendly action name.
        action_type: Type discriminator for the action.
        description: Human-readable description.
    """

    action_id: str
    name: str | None = None
    action_type: str
    description: str | None = None

    @field_validator("action_id")
    @classmethod
    def action_id_not_empty(cls, v: str) -> str:
        """Validate action_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("action_id cannot be empty or whitespace")
        return v.strip()


class GenericActionContext(ActionContextBase):
    """Generic action projection for templates.

    Attributes:
        action_type: Discriminator field, always 'generic'.
        operation: The operation being performed.
    """

    action_type: Literal["generic"] = "generic"
    operation: str


class CommandActionContext(ActionContextBase):
    """Command action projection for templates.

    Excludes actual command content for security in display contexts.

    Attributes:
        action_type: Discriminator field, always 'command'.
        has_command: Whether a command is defined.
        timeout_seconds: Maximum execution time.
    """

    action_type: Literal["command"] = "command"
    has_command: bool = True
    timeout_seconds: int = 300


class FileActionContext(ActionContextBase):
    """File action projection for templates.

    Attributes:
        action_type: Discriminator field, always 'file'.
        file_operation: The file operation type.
        path: Target path (may be masked for security).
    """

    action_type: Literal["file"] = "file"
    file_operation: str
    path: str


class NetworkActionContext(ActionContextBase):
    """Network action projection for templates.

    Attributes:
        action_type: Discriminator field, always 'network'.
        network_operation: The network operation type.
        protocol: Network protocol.
    """

    action_type: Literal["network"] = "network"
    network_operation: str
    protocol: str


# Discriminated union for contexts
ActionContext = Annotated[
    GenericActionContext | CommandActionContext | FileActionContext | NetworkActionContext,
    Discriminator("action_type"),
]


class ActionRef(BaseModel):
    """Minimal action reference for operations.

    Contains only the identifiers needed to reference an action.
    Used for step composition and action lookup.

    Attributes:
        action_id: Unique identifier of the action.
        action_type: Type of the action.
    """

    action_id: str
    action_type: str

    @field_validator("action_id")
    @classmethod
    def action_id_not_empty(cls, v: str) -> str:
        """Validate action_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("action_id cannot be empty or whitespace")
        return v.strip()

    @field_validator("action_type")
    @classmethod
    def action_type_not_empty(cls, v: str) -> str:
        """Validate action_type is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("action_type cannot be empty or whitespace")
        return v.strip()
