"""Small bounded ASGI transport helpers shared by two private listeners."""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from shared.model_access import ContractError
from shared.model_access.messages import JsonObject

ASGIScope = dict[str, Any]
ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]
MAX_HEADER_BYTES = 32_768
MAX_HEADERS = 64
_RESPONSE_START = "http.response.start"
_INVALID_HEADERS = "http.invalid_headers"


class ResponseWriter:
    """Bound backpressure and prevent a second HTTP response after a failure."""

    def __init__(self, send: Send) -> None:
        self.send = send
        self.started = False
        self.finished = False

    async def __call__(self, message: ASGIMessage) -> None:
        if self.finished or (message["type"] == _RESPONSE_START and self.started):
            raise OSError("http.response_closed")
        if message["type"] == _RESPONSE_START:
            self.started = True
        async with asyncio.timeout(5):
            await self.send(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            self.finished = True


def headers(scope: ASGIScope) -> dict[str, str]:
    """Reject ambiguous duplicate security headers and compressed request bodies."""
    result = {}
    total = 0
    for index, (name, value) in enumerate(scope.get("headers", ())):
        total += len(name) + len(value) + 4
        if index >= MAX_HEADERS or total > MAX_HEADER_BYTES:
            raise ContractError(_INVALID_HEADERS)
        key, text = _header_pair(name, value)
        if key in result:
            raise ContractError(_INVALID_HEADERS)
        result[key] = text
    _validate_framing(result)
    return result


def _header_pair(name: bytes, value: bytes) -> tuple[str, str]:
    """Decode one bounded ASCII header without accepting control bytes."""
    if not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", name):
        raise ContractError(_INVALID_HEADERS)
    key = name.decode("ascii").lower()
    text = value.decode("ascii")
    if len(text) > 16_384 or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ContractError(_INVALID_HEADERS)
    return key, text


def _validate_framing(result: dict[str, str]) -> None:
    """Reject conflicting framing, encoding, and guest credentials."""
    if result.get("content-encoding", "identity") != "identity":
        raise ContractError("http.encoding_unsupported")
    if "content-length" in result and "transfer-encoding" in result:
        raise ContractError(_INVALID_HEADERS)
    if "content-length" in result and not re.fullmatch(r"\d{1,10}", result["content-length"], flags=re.ASCII):
        raise ContractError(_INVALID_HEADERS)
    if result.get("transfer-encoding", "chunked") != "chunked":
        raise ContractError(_INVALID_HEADERS)
    if "authorization" in result and "x-api-key" in result:
        raise ContractError("credential.unavailable")


async def body(receive: Receive, *, limit: int) -> bytes:
    """Reject chunked overflow and slow/disconnected uploads before parsing."""
    value = bytearray()
    async with asyncio.timeout(5):
        while True:
            message = await receive()
            if message["type"] != "http.request":
                raise ContractError("http.disconnected")
            chunk = message.get("body", b"")
            if len(value) + len(chunk) > limit:
                raise ContractError("http.too_large")
            value.extend(chunk)
            if not message.get("more_body", False):
                return bytes(value)


async def json_response(send: Send, status: int, value: JsonObject) -> None:
    """No cache or reflected upstream headers; callers supply safe error codes."""
    payload = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    await send(
        {
            "type": _RESPONSE_START,
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
