"""Base schemas for the Shifter DSL.

These Pydantic models provide the foundation for all entity specs in the system.
SpecBase is the root of the spec hierarchy - all entity specs inherit from it.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class SpecBase(BaseModel):
    """Base specification for all entities.

    All entity specs inherit from this class, ensuring consistent
    validation for common fields like name.

    Attributes:
        name: User-friendly entity name (optional, subclasses may require it).
    """

    name: str | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str | None) -> str | None:
        """Validate name is not empty or whitespace if provided."""
        if v is None:
            return v
        if not v.strip():
            raise ValueError("name cannot be empty or whitespace")
        return v.strip()
