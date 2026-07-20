"""WebSocket account-origin authorization boundary."""

from collections.abc import Awaitable, Callable

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser, User

type ASGIMessage = dict[str, object]
type ASGIScope = dict[str, object]
type ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
type ASGISend = Callable[[ASGIMessage], Awaitable[None]]
type ASGIApplication = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]


class CTFAccountWebSocketBoundary:
    """Close every platform socket for temporary CTF accounts."""

    def __init__(self, application: ASGIApplication) -> None:
        self.application = application

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        user = scope.get("user")
        if isinstance(user, (User, AnonymousUser)) and await self._is_ctf_account(user):
            await send({"type": "websocket.close", "code": 4403})
            return
        await self.application(scope, receive, send)

    @database_sync_to_async
    def _is_ctf_account(self, user: User | AnonymousUser) -> bool:
        from management.services import is_temporary_ctf_account

        return is_temporary_ctf_account(user)
