"""Closed replies for the private control protocol, without application imports."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, Field, SecretStr, StrictBool, StrictInt

from shared.model_access.core_models import ClosedModel, Identifier
from shared.model_access.credentials import ModelAccessAuthorization, ModelTokenPair
from shared.model_access.messages import JsonObject
from shared.model_access.provider_runtime import SourceExecutionProjection


def _affirmative(value: bool) -> bool:
    """Require an explicit positive acknowledgement for authority-bearing replies."""
    if not value:
        raise ValueError("control authority must be affirmative")
    return value


type Affirmative = Annotated[StrictBool, AfterValidator(_affirmative)]


class ReadyReply(ClosedModel):
    """Readiness proves a checked control dependency, not just a listening socket."""

    ready: StrictBool


class ReservationReply(ClosedModel):
    """The committed identity and cost of one reserved request."""

    request_uuid: UUID
    canonical_request_cost: Annotated[StrictInt, Field(ge=0)]
    account_refs: Annotated[tuple[Identifier, ...], Field(max_length=1024)] = ()


class CommitReply(ClosedModel):
    """The proven paid cost committed to a counted request before paid dispatch."""

    canonical_request_cost: Annotated[StrictInt, Field(ge=0)]


class DispatchReply(ClosedModel):
    """Fresh transport authority, never a response replay token."""

    dispatch_token: Annotated[SecretStr, Field(min_length=1, max_length=128)]
    deadline: AwareDatetime


class ContinuationReply(ClosedModel):
    """A fresh continuation revision with an explicit expiry."""

    revision: Annotated[StrictInt, Field(gt=0)]
    deadline: AwareDatetime


class CheckReply(ClosedModel):
    """Only a positive lease check authorizes transport."""

    valid: Affirmative


class SettlementReply(ClosedModel):
    """The proven charge accepted by Engine."""

    charge: Annotated[StrictInt, Field(ge=0)]


class UnknownReply(ClosedModel):
    """Engine has retained the uncertain liability."""

    recorded: Affirmative


class ReleaseReply(ClosedModel):
    """Engine has accepted a proven pre-dispatch release."""

    released: Affirmative


def validate_control_reply(route: str, request: JsonObject, reply: JsonObject) -> JsonObject:
    """Reject malformed, extended or expired authority before using any fields."""
    routes: dict[str, type[ClosedModel]] = {
        "ready": ReadyReply,
        "authenticate": ModelAccessAuthorization,
        "exchange": ModelTokenPair,
        "refresh": ModelTokenPair,
        "reserve": ReservationReply,
        "commit": CommitReply,
        "source": SourceExecutionProjection,
    }
    actions: dict[str, type[ClosedModel]]
    model = routes.get(route)
    if route == "advance":
        actions = {"dispatch": DispatchReply, "continue": ContinuationReply, "check": CheckReply}
        model = actions[request["action"]]
    elif route == "finish":
        actions = {"settle": SettlementReply, "unknown": UnknownReply, "release": ReleaseReply}
        model = actions[request["action"]]
    if model is None:
        raise ValueError
    parsed = model.model_validate(reply)
    if isinstance(parsed, (DispatchReply, ContinuationReply)) and parsed.deadline <= datetime.now(UTC):
        raise ValueError
    return reply
