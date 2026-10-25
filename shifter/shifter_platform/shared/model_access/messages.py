"""Bounded text/tool Messages subset with no request-controlled transport fields."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictFloat, StrictInt, ValidationError

from shared.model_access.catalog import ContractError
from shared.model_access.core_models import AccessLimits, ClosedModel, Identifier

JsonObject = dict[str, Any]

MAX_MESSAGE_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 8_000_000


class TextBlock(ClosedModel):
    """Plain text without cache, image, document or provider-specific extensions."""

    type: Literal["text"]
    text: Annotated[str, Field(max_length=MAX_MESSAGE_BYTES)]


class ToolUseBlock(ClosedModel):
    """A local tool request; the broker never executes the named tool."""

    type: Literal["tool_use"]
    id: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
    input: dict[str, JsonValue]


class ToolResultBlock(ClosedModel):
    """Only bounded text results, with no remote images or callbacks."""

    type: Literal["tool_result"]
    tool_use_id: Annotated[str, Field(min_length=1, max_length=128)]
    content: str | Annotated[list[TextBlock], Field(max_length=128)]
    is_error: StrictBool = False


ContentBlock = Annotated[TextBlock | ToolUseBlock | ToolResultBlock, Field(discriminator="type")]


class Message(ClosedModel):
    """A supported client conversation turn."""

    role: Literal["user", "assistant"]
    content: str | Annotated[list[ContentBlock], Field(min_length=1, max_length=128)]


class LocalTool(ClosedModel):
    """Declarative client-local tool schema, never a server-side tool capability."""

    name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
    description: Annotated[str, Field(max_length=16_384)] = ""
    input_schema: dict[str, JsonValue]


class ToolChoice(ClosedModel):
    """Supported Messages tool-selection vocabulary."""

    type: Literal["auto", "any", "tool", "none"]
    name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")] | None = None
    disable_parallel_tool_use: StrictBool = False


class CountTokensRequest(ClosedModel):
    """Shared prompt shape for free, still rate/concurrency-budgeted counting."""

    model: Identifier
    messages: Annotated[list[Message], Field(min_length=1, max_length=512)]
    system: str | Annotated[list[TextBlock], Field(max_length=128)] | None = None
    tools: Annotated[list[LocalTool], Field(max_length=128)] | None = None
    tool_choice: ToolChoice | None = None


class MessagesRequest(CountTokensRequest):
    """Closed first-release protocol; new billable features need new bounds."""

    max_tokens: Annotated[StrictInt, Field(gt=0, le=131_072)]
    stream: StrictBool = False
    temperature: Annotated[StrictFloat, Field(ge=0, le=1)] | None = None
    top_p: Annotated[StrictFloat, Field(ge=0, le=1)] | None = None
    top_k: Annotated[StrictInt, Field(ge=0, le=1000)] | None = None
    stop_sequences: Annotated[list[Annotated[str, Field(max_length=256)]], Field(max_length=16)] | None = None


ResponseContentBlock = Annotated[TextBlock | ToolUseBlock, Field(discriminator="type")]


class MessagesResponse(BaseModel):
    """Closed qualified assistant reply used to validate provider responses.

    Content is restricted to the qualified text and local ``tool_use`` blocks, so
    an unqualified cost- or semantics-changing block (for example ``thinking``) is
    rejected before it reaches the participant. Unknown top-level fields are
    tolerated and ignored rather than rejected, so a benign additive provider
    field never blocks a working range; cost-bearing usage is enforced separately
    by the usage normalizer, and the qualified surface is pinned by the wire corpus.
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["message"]
    role: Literal["assistant"]
    content: Annotated[list[ResponseContentBlock], Field(min_length=1, max_length=512)]
    stop_reason: Annotated[str, Field(min_length=1, max_length=64)]
    usage: dict[str, JsonValue]


def strict_json(raw: bytes, *, limit: int = MAX_MESSAGE_BYTES) -> JsonObject:
    """Bound parsing before validation; reject duplicate keys, nonfinite and depth."""
    if len(raw) > limit:
        raise ContractError("messages.too_large")

    def pairs(items: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
        """Reject duplicate JSON members before constructing their mapping."""
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate member")
            result[key] = value
        return result

    def nonfinite(_: str) -> NoReturn:
        """Reject JSON decoder extensions for nonfinite numbers."""
        raise ValueError("nonfinite")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                raise ValueError("depth")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        if not isinstance(value, dict):
            raise ValueError("object required")
        return value
    except (ValueError, RecursionError):
        raise ContractError("messages.invalid_json") from None


def parse_messages(raw: bytes, *, count_only: bool, limits: AccessLimits) -> CountTokensRequest | MessagesRequest:
    """Reject unsupported fields without including participant data in errors."""
    value = strict_json(raw, limit=min(MAX_MESSAGE_BYTES, limits.max_request_bytes))
    try:
        message = (CountTokensRequest if count_only else MessagesRequest).model_validate(value)
    except ValidationError:
        raise ContractError("messages.unsupported_request") from None
    if isinstance(message, MessagesRequest) and message.max_tokens > limits.max_output_tokens:
        raise ContractError("messages.output_limit")
    return message
