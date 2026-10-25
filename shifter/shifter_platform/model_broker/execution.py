"""One broker request's reservation, streaming and terminal accounting lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import NoReturn
from uuid import uuid4

from shared.model_access import ContractError
from shared.model_access.core_models import BillingComponent
from shared.model_access.credentials import ModelAccessAuthorization
from shared.model_access.http import Receive, Send
from shared.model_access.messages import MAX_RESPONSE_BYTES, CountTokensRequest, JsonObject, MessagesRequest
from shared.model_access.provider import ProviderUsage, VerifiedUsage

from .control import ControlClient
from .errors import NoBillableEffect
from .providers import MessagesProvider

_RESPONSE_BODY = "http.response.body"


@dataclass(frozen=True)
class BrokerRequest:
    """Authenticated request facts retained through one provider invocation."""

    message: CountTokensRequest
    authority: ModelAccessAuthorization
    token: str
    peer: str
    count_only: bool
    retry_fields: JsonObject
    deadline: float


class BrokerInvocation:
    """Settle verified usage once; interrupted billable work retains its hold."""

    def __init__(
        self,
        control: ControlClient,
        provider: MessagesProvider,
        request: BrokerRequest,
        receive: Receive,
        send: Send,
        *,
        drain: asyncio.Event,
    ) -> None:
        self.control, self.provider, self.request = control, provider, request
        self.receive, self.send = receive, send
        self.drain = drain
        self.request_uuid = str(uuid4())
        self.identity = {"token": request.token, "transport_peer": request.peer, "request_uuid": self.request_uuid}
        self.dispatched = False
        self.started = False
        self.reserved = False
        self.count_first = False
        self.committed = False
        self.settled = False
        self.tasks: list[asyncio.Task[object]] = []

    async def run(self) -> None:
        """Reserve before dispatch and finalize accounting even on disconnect."""
        try:
            async with asyncio.timeout_at(self.request.deadline):
                self.count_first = self._counts_before_dispatch()
                if not await self._reserve(count_first=self.count_first):
                    return
                await self._dispatch()
                precounted = await self._commit_proven_input(self.count_first)
                await self._settle(await self._wait_for_transfer(precounted))
                await self.send({"type": _RESPONSE_BODY, "body": b"", "more_body": False})
        except NoBillableEffect as exc:
            if self.reserved:
                await self._settle(self._no_effect_usage(exc))
            raise
        except Exception:
            await self._cancel_transport()
            if not self.started:
                raise
            await self._interrupted()
        finally:
            await self._finalize()

    def _counts_before_dispatch(self) -> bool:
        """A paid request proves its input first only when counting is actually enabled.

        The provider must support counting and this grant's alias must carry the
        ``token-count`` capability, which is enabled together with the zero-cost
        ``request`` price the count reservation needs. Without it the request keeps
        the conservative full-context reservation rather than failing to admit.
        """
        if self.request.count_only or not self.provider.capabilities().token_counting:
            return False
        shard = self.request.authority.aliases.get(self.request.message.model)
        return shard is not None and "token-count" in shard.capabilities

    async def _reserve(self, *, count_first: bool) -> bool:
        """Deduplicate before any potentially billable provider work starts.

        A counting paid request reserves the free count bound first so a completed
        retry deduplicates before the provider is ever counted; the proven input
        spend is committed to this same reservation after the count.
        """
        bounded = self.provider.message_billing_bound(
            self.request.message, count_only=self.request.count_only or count_first
        )
        reserved = await self.control.call(
            "reserve",
            {
                **self.identity,
                "logical_alias": self.request.message.model,
                "billing_bound": bounded.model_dump(mode="json"),
                **self.request.retry_fields,
            },
        )
        if reserved["request_uuid"] != self.request_uuid:
            from shared.model_access.http import json_response

            await json_response(self.send, 409, {"type": "completed", "request_id": reserved["request_uuid"]})
            return False
        self.reserved = True
        return True

    async def _commit_proven_input(self, counting: bool) -> int | None:
        """Prove the input count under the dispatch lease and commit its spend hold.

        Routine small prompts must not be denied because the reservation assumed
        the full physical context window. The count is an accounted, authority-
        checked provider operation; ``commit`` then narrows this exact request's
        input units to the proven count before the paid transfer. Providers with
        no free count endpoint keep the conservative full-context reservation.
        """
        if not counting:
            return None
        tokens = await self.provider.count(self.request.message, before_transport=self._before_transport)
        paid = self.provider.message_billing_bound(self.request.message, count_only=False, input_tokens=tokens)
        await self.control.call("commit", {**self.identity, "billing_bound": paid.model_dump(mode="json")})
        self.committed = True
        return tokens

    def _no_effect_usage(self, exc: NoBillableEffect) -> ProviderUsage:
        """Terminalize a pre-commit count-first failure as its free count, not paid liability.

        Before commit the reservation still carries only the zero-cost request bound,
        so a failed count settles that free operation rather than leaving a paid
        input/output reservation stuck as unknown with a retained obligation.
        """
        if self.count_first and not self.committed:
            return ProviderUsage(
                items=(VerifiedUsage(component=BillingComponent.REQUEST, units=0, provider_verified=True),)
            )
        return exc.usage

    async def _dispatch(self) -> None:
        """Fence provider dispatch with a fresh, checked accounting lease."""
        lease = await self.control.call("advance", {**self.identity, "action": "dispatch"})
        self.dispatched = True
        await self.control.call(
            "advance", {**self.identity, "action": "check", "dispatch_token": lease["dispatch_token"]}
        )

    async def _wait_for_transfer(self, precounted: int | None) -> ProviderUsage:
        """End the transfer when either peer disconnects or its grant is revoked."""
        work = asyncio.create_task(self._transfer(precounted))
        heartbeat = asyncio.create_task(self._renew())
        disconnect = asyncio.create_task(self._disconnected())
        draining = asyncio.create_task(self._drained())
        self.tasks = [work, heartbeat, disconnect, draining]
        done, _ = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in (heartbeat, disconnect, draining):
            if task in done:
                task.result()
        return work.result()

    async def _settle(self, usage: ProviderUsage) -> None:
        """Mark settlement only after Engine accepts the verified usage."""
        await self.control.call(
            "finish", {"request_uuid": self.request_uuid, "action": "settle", "usage": usage.model_dump(mode="json")}
        )
        self.settled = True

    async def _interrupted(self) -> None:
        """Close a started stream with a fixed error and no upstream diagnostics."""
        payload = b""
        if isinstance(self.request.message, MessagesRequest) and self.request.message.stream:
            payload = (
                b'\n\nevent: error\ndata: {"type":"error",'
                b'"error":{"type":"api_error","message":"broker.interrupted"}}\n\n'
            )
        with suppress(OSError, TimeoutError):
            async with asyncio.timeout(1):
                await self.send(
                    {
                        "type": _RESPONSE_BODY,
                        "body": payload,
                        "more_body": False,
                    }
                )

    async def _finalize(self) -> None:
        """Cancel sibling tasks and preserve uncertain provider liability."""
        await self._cancel_transport()
        if self.reserved and not self.settled:
            with suppress(Exception):
                await self.control.call(
                    "finish", {"request_uuid": self.request_uuid, "action": "unknown" if self.dispatched else "release"}
                )

    async def _cancel_transport(self) -> None:
        """Fence upstream before attempting any downstream error notification."""
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task

    async def _before_transport(self) -> str:
        """Recheck authority immediately before every upstream HTTP operation."""
        result = await self.control.call("advance", {**self.identity, "action": "continue"})
        return str(result["deadline"])

    async def _transfer(self, precounted: int | None = None) -> ProviderUsage:
        """Forward bounded chunks and require usage before terminal success."""
        total = 0
        async with self.provider.invoke(
            self.request.message,
            count_only=self.request.count_only,
            before_transport=self._before_transport,
            precounted=precounted,
        ) as response:
            await self.send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", response.content_type.encode()),
                        (b"cache-control", b"no-store"),
                        (b"x-request-id", self.request_uuid.encode()),
                    ],
                }
            )
            self.started = True
            async for chunk in response.chunks:
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise ContractError("provider.response_limit")
                await self.send({"type": _RESPONSE_BODY, "body": chunk, "more_body": True})
            if response.usage is None:
                raise ContractError("provider.incomplete_usage")
            return response.usage

    async def _renew(self) -> None:
        """Keep streaming authority checked until completion or cancellation."""
        while True:
            await asyncio.sleep(2)
            await self.control.call("advance", {**self.identity, "action": "continue"})

    async def _disconnected(self) -> NoReturn:
        """Stop provider transport when the participant disconnects."""
        while True:
            if (await self.receive())["type"] == "http.disconnect":
                raise ContractError("http.disconnected")

    async def _drained(self) -> NoReturn:
        """Terminate transport as soon as process drain starts."""
        await self.drain.wait()
        raise ContractError("broker.draining")
