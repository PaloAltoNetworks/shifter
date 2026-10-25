"""Verified TLS, bounded private Engine calls with workload identity on each call."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from shared.model_access import ContractError
from shared.model_access.control_wire import validate_control_reply
from shared.model_access.messages import JsonObject, strict_json


class ControlClient:
    """No redirects, environment proxies, implicit retries or guest-chosen URLs."""

    def __init__(self, *, url: str, ca_file: str, identity: Callable[[], Awaitable[str]]) -> None:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path
        ):
            raise ValueError("control URL must be an HTTPS origin")
        self.url = url
        self.identity = identity
        context = ssl.create_default_context(cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        self.client = httpx.AsyncClient(
            verify=context,
            trust_env=False,
            follow_redirects=False,
            timeout=2,
            limits=httpx.Limits(max_connections=128),
        )

    async def call(self, route: str, payload: JsonObject) -> JsonObject:
        if route not in {
            "ready",
            "authenticate",
            "source",
            "exchange",
            "refresh",
            "reserve",
            "commit",
            "advance",
            "finish",
        }:
            raise ContractError("control.invalid_route")
        try:
            async with asyncio.timeout(2):
                assertion = await self.identity()
                async with self.client.stream(
                    "POST", f"{self.url}/control/v1/{route}", json=payload, headers={"authorization": assertion}
                ) as response:
                    result = await _read_response(response)
                    try:
                        return validate_control_reply(route, payload, result)
                    except (ValueError, TypeError, KeyError):
                        raise ContractError("control.invalid_response") from None
        except (httpx.HTTPError, TimeoutError):
            raise ContractError("control.unavailable") from None

    async def close(self) -> None:
        await self.client.aclose()


async def _read_response(response: httpx.Response) -> JsonObject:
    """Bound control replies and expose only Engine's closed error vocabulary."""
    value = bytearray()
    async for chunk in response.aiter_bytes():
        if len(value) + len(chunk) > 131_072:
            raise ContractError("control.invalid_response")
        value.extend(chunk)
    data = strict_json(bytes(value), limit=131_072)
    if response.status_code != 200:
        code = data.get("error", "")
        if not isinstance(code, str) or code not in {
            "credential.unavailable",
            "credential.rate_limited",
            "request.budget_exceeded",
            "request.revoked",
            "request.intent_conflict",
            "request.in_progress_or_unknown",
        }:
            code = "control.unavailable"
        raise ContractError(code)
    return data
