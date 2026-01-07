"""App DSL schemas for CMS data contracts.

These Pydantic models define the App DSL - a layered schema system where:
- Specs (OSAppSpec, NGFWAppSpec, etc.) are type-specific creation schemas
- Projections (AppContext, AppRef) provide tailored views for specific use cases

App types: os, ngfw, agent, other.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, field_validator

from .base import SpecBase

# =============================================================================
# App Specs - type-specific creation schemas
# =============================================================================


class AppSpecBase(SpecBase):
    """Base specification for all app types.

    Extends SpecBase with fields common to all apps.

    Attributes:
        name: User-friendly app name (inherited from SpecBase, optional).
    """

    pass


class OSAppSpec(AppSpecBase):
    """Specification for creating an OS app.

    Attributes:
        name: User-friendly app name (inherited).
        app_type: Discriminator field, always 'os'.
    """

    app_type: Literal["os"] = "os"


class NGFWAppSpec(AppSpecBase):
    """Specification for creating an NGFW app.

    Attributes:
        name: User-friendly app name (inherited).
        app_type: Discriminator field, always 'ngfw'.
    """

    app_type: Literal["ngfw"] = "ngfw"


class AgentAppSpec(AppSpecBase):
    """Specification for creating an Agent app.

    Attributes:
        name: User-friendly app name (inherited).
        app_type: Discriminator field, always 'agent'.
    """

    app_type: Literal["agent"] = "agent"


class OtherAppSpec(AppSpecBase):
    """Specification for creating an Other app.

    Attributes:
        name: User-friendly app name (inherited).
        app_type: Discriminator field, always 'other'.
    """

    app_type: Literal["other"] = "other"


# =============================================================================
# Projections - tailored views of the App DSL kernel
# =============================================================================


class AppContextBase(BaseModel):
    """Base projection for all app types.

    Contains fields common to all app contexts.
    Type-specific contexts extend this with their own fields.

    Attributes:
        app_id: Unique identifier of the app.
        name: User-friendly app name.
    """

    app_id: int
    name: str

    @field_validator("app_id")
    @classmethod
    def app_id_positive(cls, v: int) -> int:
        """Validate app_id is a positive integer."""
        if v <= 0:
            raise ValueError("app_id must be a positive integer")
        return v


class OSAppContext(AppContextBase):
    """OS app projection for templates.

    Attributes:
        app_type: Discriminator field, always 'os'.
    """

    app_type: Literal["os"] = "os"


class NGFWAppContext(AppContextBase):
    """NGFW app projection for templates.

    Attributes:
        app_type: Discriminator field, always 'ngfw'.
    """

    app_type: Literal["ngfw"] = "ngfw"


class AgentAppContext(AppContextBase):
    """Agent app projection for templates.

    Attributes:
        app_type: Discriminator field, always 'agent'.
    """

    app_type: Literal["agent"] = "agent"


class OtherAppContext(AppContextBase):
    """Other app projection for templates.

    Attributes:
        app_type: Discriminator field, always 'other'.
    """

    app_type: Literal["other"] = "other"


# Discriminated union - Pydantic auto-routes based on app_type field
AppContext = Annotated[
    OSAppContext | NGFWAppContext | AgentAppContext | OtherAppContext,
    Discriminator("app_type"),
]


class AppRef(BaseModel):
    """Minimal app reference for operations.

    Contains only the identifiers needed to reference an app.
    Used for delete operations and status checks.

    Attributes:
        app_id: Unique identifier of the app.
    """

    app_id: int

    @field_validator("app_id")
    @classmethod
    def app_id_positive(cls, v: int) -> int:
        """Validate app_id is a positive integer."""
        if v <= 0:
            raise ValueError("app_id must be a positive integer")
        return v
