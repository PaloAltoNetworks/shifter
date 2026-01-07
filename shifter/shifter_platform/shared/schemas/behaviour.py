"""Behaviour DSL schemas for CMS data contracts.

These Pydantic models define the Behaviour DSL - a layered schema system where:
- Specs (AttackBehaviourSpec, etc.) are type-specific creation schemas
- Projections (BehaviourContext, BehaviourRef) provide tailored views for specific use cases

Behaviour types: attack.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, field_validator

from .base import SpecBase

# =============================================================================
# Behaviour Specs - type-specific creation schemas
# =============================================================================


class BehaviourSpecBase(SpecBase):
    """Base specification for all behaviour types.

    Extends SpecBase with fields common to all behaviours.

    Attributes:
        name: User-friendly behaviour name (inherited from SpecBase, optional).
    """

    pass


class AttackBehaviourSpec(BehaviourSpecBase):
    """Specification for creating an attack behaviour.

    Attributes:
        name: User-friendly behaviour name (inherited).
        behaviour_type: Discriminator field, always 'attack'.
    """

    behaviour_type: Literal["attack"] = "attack"


# =============================================================================
# Projections - tailored views of the Behaviour DSL kernel
# =============================================================================


class BehaviourContextBase(BaseModel):
    """Base projection for all behaviour types.

    Contains fields common to all behaviour contexts.
    Type-specific contexts extend this with their own fields.

    Attributes:
        behaviour_id: Unique identifier of the behaviour.
        name: User-friendly behaviour name.
    """

    behaviour_id: int
    name: str

    @field_validator("behaviour_id")
    @classmethod
    def behaviour_id_positive(cls, v: int) -> int:
        """Validate behaviour_id is a positive integer."""
        if v <= 0:
            raise ValueError("behaviour_id must be a positive integer")
        return v


class AttackBehaviourContext(BehaviourContextBase):
    """Attack behaviour projection for templates.

    Attributes:
        behaviour_type: Discriminator field, always 'attack'.
    """

    behaviour_type: Literal["attack"] = "attack"


# Discriminated union - Pydantic auto-routes based on behaviour_type field
BehaviourContext = Annotated[
    AttackBehaviourContext,
    Discriminator("behaviour_type"),
]


class BehaviourRef(BaseModel):
    """Minimal behaviour reference for operations.

    Contains only the identifiers needed to reference a behaviour.
    Used for delete operations and status checks.

    Attributes:
        behaviour_id: Unique identifier of the behaviour.
    """

    behaviour_id: int

    @field_validator("behaviour_id")
    @classmethod
    def behaviour_id_positive(cls, v: int) -> int:
        """Validate behaviour_id is a positive integer."""
        if v <= 0:
            raise ValueError("behaviour_id must be a positive integer")
        return v
