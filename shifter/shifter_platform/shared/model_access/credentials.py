"""Secret-bearing control responses with redacted representations."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr, StrictInt

from shared.model_access.core_models import AccessLimits, ClosedModel, Identifier, ModelShard

OpaqueToken = Annotated[SecretStr, Field(min_length=80, max_length=80)]


class ModelEnrollment(ClosedModel):
    """Returned once to the authenticated generation-bound provisioner."""

    grant_id: UUID
    enrollment_token: SecretStr
    expires_at: datetime


class ModelTokenPair(ClosedModel):
    """Returned once by exchange or serialized refresh; never persisted raw."""

    access_token: OpaqueToken
    refresh_token: OpaqueToken
    access_expires_at: AwareDatetime
    hard_expires_at: AwareDatetime


class ModelAccessAuthorization(ClosedModel):
    """Current Engine authority returned to the broker, without provider secrets."""

    allocation_id: UUID
    operation_id: UUID
    grant_epoch: Annotated[StrictInt, Field(gt=0)]
    aliases: Annotated[dict[Identifier, ModelShard], Field(min_length=1, max_length=128)]
    limits: AccessLimits
    hard_expires_at: AwareDatetime
