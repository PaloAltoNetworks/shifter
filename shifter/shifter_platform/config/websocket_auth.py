"""WebSocket account-origin authorization boundary."""

from collections.abc import Awaitable, Callable

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser, User

from shared.enums import WebSocketCloseCode
from shared.remote_access import TERMINAL_TARGET_PATH_RE

type ASGIMessage = dict[str, object]
type ASGIScope = dict[str, object]
type ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
type ASGISend = Callable[[ASGIMessage], Awaitable[None]]
type ASGIApplication = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]

_WEBSOCKET_CLOSE = "websocket.close"
_WEBSOCKET_DISCONNECT = "websocket.disconnect"


class CredentialSessionWebSocketBoundary:
    """Apply the HTTP assurance check at connection and every socket message."""

    def __init__(self, application: ASGIApplication) -> None:
        self.application = application

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        async def allowed() -> bool:
            """Revalidate the session against current account and provider state."""
            from config.session_credentials import validate_socket_session

            return await database_sync_to_async(validate_socket_session)(scope)

        if not await allowed():
            await send({"type": _WEBSOCKET_CLOSE, "code": WebSocketCloseCode.NOT_AUTHENTICATED})
            return

        closed = False

        async def close_revoked() -> None:
            """Close the socket once when its credential is no longer valid."""
            nonlocal closed
            if not closed:
                closed = True
                await send({"type": _WEBSOCKET_CLOSE, "code": WebSocketCloseCode.NOT_AUTHENTICATED})

        async def guarded_receive() -> ASGIMessage:
            """Reject the next client message after session revocation."""
            if closed:
                return {"type": _WEBSOCKET_DISCONNECT, "code": WebSocketCloseCode.NOT_AUTHENTICATED}
            message = await receive()
            if message.get("type") != _WEBSOCKET_DISCONNECT and not await allowed():
                await close_revoked()
                return {"type": _WEBSOCKET_DISCONNECT, "code": WebSocketCloseCode.NOT_AUTHENTICATED}
            return message

        async def guarded_send(message: ASGIMessage) -> None:
            """Suppress application messages after session revocation."""
            nonlocal closed
            if closed:
                return
            if message.get("type") != _WEBSOCKET_CLOSE and not await allowed():
                await close_revoked()
                return
            if message.get("type") == _WEBSOCKET_CLOSE:
                closed = True
            await send(message)

        await self.application(scope, guarded_receive, guarded_send)


class CTFAccountWebSocketBoundary:
    """Restrict temporary CTF accounts to their participant terminal socket."""

    def __init__(self, application: ASGIApplication) -> None:
        self.application = application

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        user = scope.get("user")
        if isinstance(user, (User, AnonymousUser)) and await self._is_ctf_account(user):
            path = str(scope.get("path", ""))
            allowed_path = bool(TERMINAL_TARGET_PATH_RE.fullmatch(path)) or path == "/ws/notifications/"
            if not allowed_path or not await self._may_access_terminal(user):
                await send({"type": _WEBSOCKET_CLOSE, "code": 4403})
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
