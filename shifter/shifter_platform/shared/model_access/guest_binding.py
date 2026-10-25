"""Byte-free guest enrollment projection for one admitted operation."""

from typing import Annotated
from uuid import UUID

from pydantic import Field

from shared.model_access.core_models import ClosedModel, Identifier


class ModelGuestBinding(ClosedModel):
    """An admitted allocation and workload role bound to one compiled guest."""

    allocation_id: UUID
    workload_role: Identifier
    target_address: Annotated[str, Field(min_length=1, max_length=1024)]
