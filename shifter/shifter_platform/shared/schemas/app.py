"""App DSL schemas for CMS data contracts.

These Pydantic models define the App DSL - a layered schema system where:
- Specs (OSAppSpec, NGFWAppSpec, etc.) are type-specific creation schemas
- Projections (AppContext, AppRef) provide tailored views for specific use cases

App types: os, ngfw, agent, other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

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
    """Specification for creating and provisioning an NGFW app.

    This schema serves dual purposes:
    1. Input from Mission Control (with credential IDs)
    2. Hydrated spec for Engine (with actual credential values)

    Input Fields (from Mission Control):
        name: User-friendly app name (required for NGFW).
        app_type: Discriminator field, always 'ngfw'.
        deployment_profile_id: ID of deployment profile credential.
        registration_method: Either "pin" or "otp".
        scm_credential_id: Required if registration_method is "pin".

    Hydrated Fields (populated by hydrator for Engine):
        instance_id: CMS Instance UUID for event correlation.
        app_id: CMS App UUID for event correlation.
        user_id: User who owns this NGFW.
        authcode: PAN-OS auth code from deployment profile.
        scm_folder_name: SCM folder name (for PIN registration).
        scm_pin_id: SCM PIN ID (for PIN registration).
        scm_pin_value: SCM PIN value/secret (for PIN registration).
        sls_region: Strata Logging Service region (for PIN registration).
        otp_value: One-time password value (for OTP registration).
        otp_folder: OTP folder path (for OTP registration).
    """

    name: str  # Required for NGFW
    app_type: Literal["ngfw"] = "ngfw"
    registration_method: Literal["pin", "otp"]

    # Input fields (credential IDs from Mission Control)
    deployment_profile_id: int | None = None
    scm_credential_id: int | None = None

    # Hydrated fields (actual values populated by hydrator for Engine)
    instance_id: UUID | None = None
    app_id: UUID | None = None
    user_id: int | None = None
    authcode: str | None = None
    scm_folder_name: str | None = None
    scm_pin_id: str | None = None
    scm_pin_value: str | None = None
    sls_region: str | None = None
    otp_value: str | None = None
    otp_folder: str | None = None

    @field_validator("deployment_profile_id")
    @classmethod
    def deployment_profile_id_positive(cls, v: int | None) -> int | None:
        """Validate deployment_profile_id is a positive integer if provided."""
        if v is not None and v <= 0:
            raise ValueError("deployment_profile_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int | None) -> int | None:
        """Validate user_id is a positive integer if provided."""
        if v is not None and v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v

    @property
    def is_hydrated(self) -> bool:
        """Return True if this spec has been hydrated with credential values."""
        return self.app_id is not None and self.authcode is not None


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


class NGFWAppContext(BaseModel):
    """NGFW app projection for templates.

    Contains fields needed for NGFW display in Mission Control.
    AWS infrastructure details are owned by Engine, not exposed here.

    Note: Does not inherit from AppContextBase because NGFW uses UUID primary key
    while other app types use int. This is an intentional design decision.

    Attributes:
        app_id: UUID of the CMS App record.
        instance_id: UUID of the CMS Instance record (for correlation).
        name: User-friendly NGFW name.
        app_type: Discriminator field, always 'ngfw'.
        status: NGFW lifecycle status (synced from Engine via events).
        created_at: When NGFW was created in CMS.
    """

    app_id: UUID
    instance_id: UUID
    name: str
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
        app_id: UUID of the CMS App record.
        instance_id: UUID of the CMS Instance record.
        is_deleted: Whether this NGFW has been soft-deleted.
    """

    app_id: UUID
    instance_id: UUID
    is_deleted: bool = False


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
