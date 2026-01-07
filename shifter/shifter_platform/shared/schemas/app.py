"""App DSL schemas for CMS data contracts.

These Pydantic models define the App DSL - a layered schema system where:
- Specs (OSAppSpec, NGFWAppSpec, etc.) are type-specific creation schemas
- Projections (AppContext, AppRef) provide tailored views for specific use cases

App types: os, ngfw, agent, other.
"""

from __future__ import annotations

from datetime import datetime
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
        name: User-friendly app name (required for NGFW).
        app_type: Discriminator field, always 'ngfw'.
        deployment_profile_id: ID of deployment profile credential.
        registration_method: Either "pin" or "otp".
        scm_credential_id: Required if registration_method is "pin".
        otp_value: Required if registration_method is "otp".
        otp_folder: Required if registration_method is "otp".
    """

    name: str  # Required for NGFW
    app_type: Literal["ngfw"] = "ngfw"
    deployment_profile_id: int
    registration_method: Literal["pin", "otp"]
    scm_credential_id: int | None = None
    otp_value: str | None = None
    otp_folder: str | None = None

    @field_validator("deployment_profile_id")
    @classmethod
    def deployment_profile_id_positive(cls, v: int) -> int:
        """Validate deployment_profile_id is a positive integer."""
        if v <= 0:
            raise ValueError("deployment_profile_id must be a positive integer")
        return v


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

    Contains fields needed for NGFW display in Mission Control.
    AWS infrastructure details are owned by Engine, not exposed here.

    Attributes:
        app_type: Discriminator field, always 'ngfw'.
        status: NGFW lifecycle status (synced from Engine via events).
        created_at: When NGFW was created in CMS.
    """

    app_type: Literal["ngfw"] = "ngfw"
    status: str
    created_at: datetime

    def get_status_display(self) -> str:
        """Human-readable status for templates."""
        return self.status.replace("_", " ").title()


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


# =============================================================================
# NGFW-specific References
# =============================================================================


class NGFWAppRef(BaseModel):
    """Minimal NGFW reference for operations.

    Contains only the identifiers needed to reference an NGFW.
    Used for provision/deprovision operations and status checks.

    Attributes:
        ngfw_id: Unique identifier of the NGFW.
        user_id: ID of the user who owns this NGFW.
        is_deleted: Whether this NGFW has been soft-deleted.
    """

    ngfw_id: int
    user_id: int
    is_deleted: bool = False

    @field_validator("ngfw_id")
    @classmethod
    def ngfw_id_positive(cls, v: int) -> int:
        """Validate ngfw_id is a positive integer."""
        if v <= 0:
            raise ValueError("ngfw_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


class LinkedRangeContext(BaseModel):
    """Range linked to an NGFW (for deprovision warnings).

    Attributes:
        range_id: ID of the linked range.
        status: Range status.
        created_at: When the range was created.
    """

    range_id: int
    status: str
    created_at: datetime

    @property
    def id(self) -> int:
        """Alias for range_id for template compatibility."""
        return self.range_id

    def get_status_display(self) -> str:
        """Human-readable status for templates."""
        return self.status.replace("_", " ").title()
