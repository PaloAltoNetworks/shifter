"""WebSocket account-origin authorization boundary."""

import re
from collections.abc import Awaitable, Callable

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser, User

type ASGIMessage = dict[str, object]
type ASGIScope = dict[str, object]
type ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
type ASGISend = Callable[[ASGIMessage], Awaitable[None]]
type ASGIApplication = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]


class CTFAccountWebSocketBoundary:
    """Restrict temporary CTF accounts to their participant terminal socket."""

    _TERMINAL_PATH = re.compile(r"^/ws/terminal/[a-f0-9-]+/$")

    def __init__(self, application: ASGIApplication) -> None:
        self.application = application

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        user = scope.get("user")
        if isinstance(user, (User, AnonymousUser)) and await self._is_ctf_account(user):
            path = str(scope.get("path", ""))
            if not self._TERMINAL_PATH.fullmatch(path) or not await self._may_access_terminal(user):
                await send({"type": "websocket.close", "code": 4403})
                return
        await self.application(scope, receive, send)

    @database_sync_to_async
    def _is_ctf_account(self, user: User | AnonymousUser) -> bool:
        from management.services import is_temporary_ctf_account

        return is_temporary_ctf_account(user)

    @database_sync_to_async
    def _may_access_terminal(self, user: User | AnonymousUser) -> bool:
        """Mirror the HTTP participant boundary for the terminal WebSocket."""
        from ctf.services.participant.accounts import live_participant_for_user
        from management.services import is_ctf_password_change_required

        return (
            isinstance(user, User)
            and live_participant_for_user(user) is not None
            and not is_ctf_password_change_required(user)
        )
