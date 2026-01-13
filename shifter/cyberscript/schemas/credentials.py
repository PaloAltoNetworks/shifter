"""Credential DSL schemas for CMS data contracts.

These Pydantic models define the Credential DSL - a layered schema system where:
- Specs (SCMCredentialSpec, DeploymentProfileSpec) are type-specific creation schemas
- Projections (CredentialContext, CredentialRef) provide tailored views for specific use cases

Used for validation and data transfer between layers.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, computed_field, field_validator

from .base import SpecBase

# =============================================================================
# Credential Specs - type-specific creation schemas
# =============================================================================


class CredentialSpecBase(SpecBase):
    """Base specification for all credential types.

    Extends SpecBase with fields common to all credentials.

    Attributes:
        name: User-friendly credential name (inherited from SpecBase, optional).
        user_id: ID of the user who owns this credential.
        expires_at: When this credential expires (optional).
    """

    user_id: int
    expires_at: datetime | None = None

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v


class SCMCredentialSpec(CredentialSpecBase):
    """Specification for creating an SCM credential.

    Attributes:
        name: User-friendly credential name (required).
        user_id: ID of the user who owns this credential (inherited).
        expires_at: When this credential expires (inherited).
        scm_folder_name: SCM folder name.
        scm_pin_id: SCM PIN identifier.
        scm_pin_value: SCM PIN value (secret).
        sls_region: SLS region.
    """

    name: str  # Required for SCM credentials
    scm_folder_name: str
    scm_pin_id: str
    scm_pin_value: str
    sls_region: Literal["americas", "europe", "japan", "asiapacific"]


class DeploymentProfileSpec(CredentialSpecBase):
    """Specification for creating a deployment profile credential.

    Attributes:
        name: User-friendly credential name (required).
        user_id: ID of the user who owns this credential (inherited).
        expires_at: When this credential expires (inherited).
        authcode: Deployment profile authcode (secret).
    """

    name: str  # Required for deployment profiles
    authcode: str


# =============================================================================
# Projections - tailored views of the Credential DSL kernel
# =============================================================================


class CredentialContextBase(BaseModel):
    """Base projection for all credential types.

    Contains fields common to all credential contexts.
    Type-specific contexts extend this with their own fields.

    Attributes:
        credential_id: Unique identifier of the credential.
        name: User-friendly credential name.
        user_id: ID of the user who owns this credential.
        created_at: When the credential was created.
        expires_at: When this credential expires (optional).
        is_deleted: Whether this credential has been soft-deleted.

    Computed properties:
        is_expired: True if credential has expired.
        expires_soon: True if credential expires within 30 days.
    """

    credential_id: int
    name: str
    user_id: int
    created_at: datetime
    expires_at: datetime | None = None
    is_deleted: bool = False

    @field_validator("credential_id")
    @classmethod
    def credential_id_positive(cls, v: int) -> int:
        """Validate credential_id is a positive integer."""
        if v <= 0:
            raise ValueError("credential_id must be a positive integer")
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
    def is_expired(self) -> bool:
        """True if credential has expired."""
        if not self.expires_at:
            return False
        return datetime.now(self.expires_at.tzinfo) > self.expires_at

    @computed_field  # type: ignore[prop-decorator]
    @property
    def expires_soon(self) -> bool:
        """True if credential expires within 30 days."""
        if not self.expires_at:
            return False
        if self.is_expired:
            return False
        now = datetime.now(self.expires_at.tzinfo)
        return self.expires_at <= now + timedelta(days=30)


class SCMCredentialContext(CredentialContextBase):
    """SCM credential projection for templates.

    Extends CredentialContextBase with SCM-specific display fields.
    Excludes sensitive values (scm_pin_value).

    Attributes:
        credential_type: Discriminator field, always 'scm'.
        scm_folder_name: SCM folder name.
        scm_pin_id: SCM PIN identifier (not the value).
        sls_region: SLS region.
    """

    credential_type: Literal["scm"] = "scm"
    scm_folder_name: str
    scm_pin_id: str
    sls_region: str


class DeploymentProfileContext(CredentialContextBase):
    """Deployment profile projection for templates.

    Extends CredentialContextBase with deployment profile display fields.
    Excludes sensitive values (full authcode).

    Attributes:
        credential_type: Discriminator field, always 'deployment_profile'.
        authcode_masked: Masked authcode for display (e.g., 'D7654***').
    """

    credential_type: Literal["deployment_profile"] = "deployment_profile"
    authcode_masked: str


# Discriminated union - Pydantic auto-routes based on credential_type field
CredentialContext = Annotated[
    SCMCredentialContext | DeploymentProfileContext,
    Discriminator("credential_type"),
]


class CredentialRef(BaseModel):
    """Minimal credential reference for operations.

    Contains only the identifiers needed to reference a credential.
    Used for delete operations and status checks.

    Attributes:
        credential_id: Unique identifier of the credential.
        user_id: ID of the user who owns this credential.
        is_deleted: Whether this credential has been soft-deleted.
    """

    credential_id: int
    user_id: int
    is_deleted: bool = False

    @field_validator("credential_id")
    @classmethod
    def credential_id_positive(cls, v: int) -> int:
        """Validate credential_id is a positive integer."""
        if v <= 0:
            raise ValueError("credential_id must be a positive integer")
        return v

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v
