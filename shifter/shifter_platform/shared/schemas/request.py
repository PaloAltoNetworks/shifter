"""Request DSL schemas for provisioning request tracking.

A Request is an explicit container for items being provisioned.
Items within a request have independent lifecycles.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from .base import SpecBase
from .range import InstanceSpec, RangeSpec


class RequestSpec(SpecBase):
    """Specification for a provisioning request.

    A request groups related items that were requested together,
    but each item has its own independent lifecycle.

    Attributes:
        request_id: Unique identifier for this request.
        user_id: User who made the request.
        created_at: When the request was created.
        items: List of specs being requested.
    """

    request_id: UUID
    user_id: int
    created_at: datetime | None = None

    # Items can be RangeSpecs or InstanceSpecs (role=ngfw for standalone NGFW)
    items: list[RangeSpec | InstanceSpec] = Field(default_factory=list)

    @field_validator("user_id")
    @classmethod
    def user_id_positive(cls, v: int) -> int:
        """Validate user_id is a positive integer."""
        if v <= 0:
            raise ValueError("user_id must be a positive integer")
        return v
