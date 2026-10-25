"""Closed text/local-tool translation between Messages and Responses APIs."""

import json
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass, field

from shared.model_access import ContractError
from shared.model_access.messages import JsonObject, strict_json

from .provider_usage import usage_from_message, vertex_events

UNSUPPORTED_REQUEST = "messages.unsupported_request"


INVALID_RESPONSE = "provider.invalid_response"


INVALID_STREAM = "provider.invalid_stream"
BlockMap = dict[tuple[int, int], tuple[int, str]]
BlockKeys = set[tuple[int, int]]


def responses_request(payload: JsonObject, *, model: str, count_only: bool) -> JsonObject:
    """Preserve the complete prompt and local tools; never enable hosted tools."""
    if payload.get("top_k") is not None or payload.get("stop_sequences"):
        raise ContractError(UNSUPPORTED_REQUEST)
    inputs = _response_inputs(payload["messages"])
    result: JsonObject = {"model": model, "input": inputs}
    if payload.get("system") is not None:
        system = payload["system"]
        result["instructions"] = system if isinstance(system, str) else "\n".join(item["text"] for item in system)
    if payload.get("tools"):
        result["tools"] = [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["input_schema"],
                "strict": False,
            }
            for tool in payload["tools"]
        ]
    _request_tool_choice(payload, result)
    if not count_only:
        _request_generation_options(payload, result)
    return result


def _request_tool_choice(payload: JsonObject, result: JsonObject) -> None:
    """Translate local tool choice without permitting hosted tools."""
    choice = payload.get("tool_choice")
    if choice:
        if choice["type"] == "tool":
            if not choice.get("name"):
                raise ContractError(UNSUPPORTED_REQUEST)
            result["tool_choice"] = {"type": "function", "name": choice["name"]}
        else:
            result["tool_choice"] = {"any": "required", "auto": "auto", "none": "none"}[choice["type"]]
        result["parallel_tool_calls"] = not choice.get("disable_parallel_tool_use", False)


def _request_generation_options(payload: JsonObject, result: JsonObject) -> None:
    """Disable storage and truncation while preserving supported sampling options."""
    if payload["max_tokens"] < 16:
        raise ContractError(UNSUPPORTED_REQUEST)
    result.update(
        store=False,
        stream=payload.get("stream", False),
        max_output_tokens=payload["max_tokens"],
        truncation="disabled",
    )
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            result[key] = payload[key]


def _response_inputs(messages: list[JsonObject]) -> list[JsonObject]:
    """Translate complete local-tool history without server-side state."""
    inputs = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            inputs.append({"role": message["role"], "content": content})
            continue
        for block in content:
            inputs.append(_input_block(block, message["role"]))
    return inputs


def _input_block(block: JsonObject, role: str) -> JsonObject:
    """Translate one text or local-tool history block with its original role."""
    kind = block["type"]
    if kind == "text":
        result = {"role": role, "content": block["text"]}
    elif kind == "tool_use" and role == "assistant":
        result = {
            "type": "function_call",
            "call_id": block["id"],
            "name": block["name"],
            "arguments": json.dumps(block["input"], separators=(",", ":")),
        }
    elif kind == "tool_result" and role == "user":
        output = block["content"]
        if not isinstance(output, str):
            output = "\n".join(item["text"] for item in output)
        if block.get("is_error"):
            output = "Tool execution failed:\n" + output
        result = {"type": "function_call_output", "call_id": block["tool_use_id"], "output": output}
    else:
        raise ContractError(UNSUPPORTED_REQUEST)
    return result


def response_message(value: JsonObject, *, model: str) -> JsonObject:
    """Include reasoning in billed output; reject missing or failed usage."""
    value = _object(value)
    normalized_usage = _response_usage(value)
    content = []
    output = value.get("output")
    if not isinstance(output, list) or len(output) > 256:
        raise ContractError(INVALID_RESPONSE)
    for item in output:
        content.extend(_output_item(_object(item)))
    reason = "end_turn"
    if value.get("status") == "incomplete":
        reason = "max_tokens"
    elif any(block["type"] == "tool_use" for block in content):
        reason = "tool_use"
    return {
        "id": value.get("id", ""),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": reason,
        "stop_sequence": None,
        "usage": normalized_usage,
    }


def _response_usage(value: JsonObject) -> JsonObject:
    """Accept terminal responses only and include cached input and reasoning usage."""
    status = value.get("status")
    incomplete = _object(value.get("incomplete_details") or {})
    if status != "completed" and not (status == "incomplete" and incomplete.get("reason") == "max_output_tokens"):
        raise ContractError("provider.incomplete_response")
    usage = value.get("usage")
    if not isinstance(usage, dict):
        raise ContractError("provider.incomplete_usage")
    # Responses input_tokens already includes cached input, and output_tokens
    # already includes reasoning. No discounted or hidden component is omitted.
    normalized_usage = {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}
    usage_from_message({"usage": normalized_usage})
    return normalized_usage


def _output_item(item: JsonObject) -> list[JsonObject]:
    """Convert supported outputs while rejecting unaccounted hosted-tool results."""
    if item.get("type") == "message":
        return [_output_text(part) for part in _parts(item.get("content"))]
    if item.get("type") == "function_call":
        _validate_call_identity(item, INVALID_RESPONSE)
        arguments = item.get("arguments")
        if not isinstance(arguments, str):
            raise ContractError(INVALID_RESPONSE)
        return [
            {"type": "tool_use", "id": item["call_id"], "name": item["name"], "input": strict_json(arguments.encode())}
        ]
    if item.get("type") != "reasoning":
        raise ContractError("provider.unsupported_response")
    return []


def _output_text(part: JsonObject) -> JsonObject:
    """Preserve both provider text and explicit refusal text."""
    kind = part.get("type")
    if not isinstance(kind, str):
        raise ContractError(INVALID_RESPONSE)
    field_name = {"output_text": "text", "refusal": "refusal"}.get(kind)
    if field_name is None or not isinstance(part.get(field_name), str):
        raise ContractError(INVALID_RESPONSE)
    return {"type": "text", "text": part[field_name]}


def _validate_call_identity(item: JsonObject, error: str) -> None:
    """Require a provider call identifier and local tool name."""
    if not isinstance(item.get("call_id"), str) or not isinstance(item.get("name"), str):
        raise ContractError(error)


_IGNORED_EVENTS = frozenset(
    {
        "response.in_progress",
        "response.output_text.done",
        "response.refusal.done",
        "response.function_call_arguments.done",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_part.done",
        "response.reasoning_summary_text.delta",
        "response.reasoning_summary_text.done",
    }
)


@dataclass
class _ResponseStream:
    """Track a single response's lifecycle and bounded content-block state."""

    model: str
    blocks: BlockMap = field(default_factory=dict)
    closed: BlockKeys = field(default_factory=set)
    started: bool = False
    stopped: bool = False

    def convert(self, event: JsonObject) -> list[JsonObject]:
        """Require start-before-content and prohibit every event after completion."""
        if self.stopped:
            raise ContractError(INVALID_STREAM)
        if event.get("type") == "response.created":
            if self.started:
                raise ContractError(INVALID_STREAM)
            self.started = True
            return [_message_start(event, self.model)]
        if not self.started:
            raise ContractError(INVALID_STREAM)
        return self._content_event(event)

    def _content_event(self, event: JsonObject) -> list[JsonObject]:
        """Dispatch content changes and publish usage only after all blocks close."""
        kind = event.get("type")
        converted: list[JsonObject] = []
        if kind in {"response.output_item.added", "response.content_part.added"}:
            block = _start_block(event, self.blocks)
            if block is not None:
                converted.append(block)
        elif kind in {"response.output_text.delta", "response.refusal.delta", "response.function_call_arguments.delta"}:
            converted.append(_delta_block(event, self.blocks, self.closed))
        elif kind in {"response.content_part.done", "response.output_item.done"}:
            converted.extend(self._close_block(event))
        elif kind in {"response.completed", "response.incomplete"}:
            final = _finished_response(event, model=self.model, blocks=self.blocks, closed=self.closed)
            converted.extend(
                [
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": final["stop_reason"], "stop_sequence": None},
                        "usage": final["usage"],
                    },
                    {"type": "message_stop"},
                ]
            )
            self.stopped = True
        elif kind not in _IGNORED_EVENTS:
            raise ContractError(INVALID_STREAM)
        return converted

    def _close_block(self, event: JsonObject) -> list[JsonObject]:
        """Close a known block once; wrapper completion carries no second stop."""
        key = _block_key(event)
        if key in self.blocks.keys() - self.closed:
            self.closed.add(key)
            return [{"type": "content_block_stop", "index": self.blocks[key][0]}]
        return []


def _message_start(event: JsonObject, model: str) -> JsonObject:
    """Start the Messages envelope without fabricating usage before completion."""
    return {
        "type": "message_start",
        "message": {
            "id": _object(event.get("response")).get("id", ""),
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    }


async def responses_events(chunks: AsyncIterable[bytes], *, model: str) -> AsyncIterator[JsonObject]:
    """Translate incremental text/tools and require the final complete usage record."""
    state = _ResponseStream(model)
    async for event in vertex_events(chunks):
        for converted in state.convert(_object(event)):
            yield converted
    if not state.stopped:
        raise ContractError("provider.incomplete_usage")


def _start_block(event: JsonObject, blocks: BlockMap) -> JsonObject | None:
    """Validate and assign a bounded stream block index."""
    item = event.get("item", {}) if event["type"] == "response.output_item.added" else event.get("part", {})
    item = _object(item)
    if item.get("type") not in {"function_call", "output_text", "refusal"}:
        if item.get("type") in {"message", "reasoning"}:
            return None
        raise ContractError("provider.unsupported_response")
    key = _block_key(event)
    if key in blocks or len(blocks) >= 256:
        raise ContractError(INVALID_STREAM)
    index = len(blocks)
    blocks[key] = (index, "tool_use" if item["type"] == "function_call" else "text")
    if item["type"] == "function_call":
        _validate_call_identity(item, INVALID_STREAM)
    block: JsonObject = (
        {"type": "text", "text": ""}
        if item["type"] in {"output_text", "refusal"}
        else {"type": "tool_use", "id": item.get("call_id"), "name": item.get("name"), "input": {}}
    )
    return {"type": "content_block_start", "index": index, "content_block": block}


def _finished_response(event: JsonObject, *, model: str, blocks: BlockMap, closed: BlockKeys) -> JsonObject:
    """Only a fully closed stream may publish the final usage record."""
    if set(blocks) != closed:
        raise ContractError(INVALID_STREAM)
    return response_message(event.get("response", {}), model=model)


def _object(value: object) -> JsonObject:
    """Require an object before inspecting provider-controlled fields."""
    if not isinstance(value, dict):
        raise ContractError(INVALID_RESPONSE)
    return value


def _parts(value: object) -> list[JsonObject]:
    """Bound response part counts and validate each object independently."""
    if not isinstance(value, list) or len(value) > 256:
        raise ContractError(INVALID_RESPONSE)
    return [_object(part) for part in value]


def _block_key(event: JsonObject) -> tuple[int, int]:
    """Validate provider indexes before using them as stream state keys."""
    output = event.get("output_index")
    content = event.get("content_index", -1)
    if type(output) is not int or not 0 <= output < 256 or type(content) is not int or not -1 <= content < 256:
        raise ContractError(INVALID_STREAM)
    return output, content


def _delta_block(event: JsonObject, blocks: BlockMap, closed: BlockKeys) -> JsonObject:
    """Accept typed deltas only for an existing, still-open block."""
    key = _block_key(event)
    if key not in blocks or key in closed or not isinstance(event.get("delta"), str):
        raise ContractError(INVALID_STREAM)
    expected = "tool_use" if event["type"] == "response.function_call_arguments.delta" else "text"
    if blocks[key][1] != expected:
        raise ContractError(INVALID_STREAM)
    delta = (
        {"type": "text_delta", "text": event["delta"]}
        if expected == "text"
        else {"type": "input_json_delta", "partial_json": event["delta"]}
    )
    return {"type": "content_block_delta", "index": blocks[key][0], "delta": delta}
