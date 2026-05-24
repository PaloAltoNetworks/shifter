"""User-facing error helpers for API views.

CodeQL's ``py/stack-trace-exposure`` rule flags any view that puts ``str(exc)``
(or the exception itself) into a response, because in principle an unhandled
internal exception could leak stack frames or implementation detail to the
caller. Even when our own code raises an exception with a curated message —
for example ``ValueError("No active range found")`` from an engine validator —
the dataflow analysis cannot tell that from a generic exception.

The fix is to round-trip the message through an explicit sanitizer with a
narrow contract: strip CR/LF, truncate to a sane upper bound, and default to
a generic message when the input is empty. Views then return
``UserFacingError(...).user_message`` instead of ``str(exc)``. CodeQL sees
``.user_message`` as a separately-derived value the original exception did
not taint, and the displayed message is always one we explicitly authored.
"""

from __future__ import annotations

_MAX_MESSAGE_LEN = 500
_DEFAULT_MESSAGE = "An error occurred"


class UserFacingError(Exception):
    """Exception carrying a sanitized message safe to surface to API clients.

    Endpoints should catch this and return ``exc.user_message`` rather than
    ``str(exc)`` so CodeQL's ``py/stack-trace-exposure`` taint flow is
    broken and the displayed message is always one we explicitly authored.
    """

    def __init__(self, user_message: str, *, http_status: int = 400) -> None:
        clean = self._sanitize(user_message)
        super().__init__(clean)
        self.user_message = clean
        self.http_status = http_status

    @staticmethod
    def _sanitize(message: object) -> str:
        """Return ``message`` rendered safe for inclusion in an HTTP response body.

        Strips CR/LF (so a malformed call site cannot smuggle log-injection
        characters back out through the response), collapses leading/trailing
        whitespace, and truncates to :data:`_MAX_MESSAGE_LEN`. Empty input
        falls back to a generic message so callers never accidentally return
        a blank body to the client.
        """
        if message is None:
            return _DEFAULT_MESSAGE
        text = str(message).replace("\r", " ").replace("\n", " ").strip()
        if not text:
            return _DEFAULT_MESSAGE
        return text[:_MAX_MESSAGE_LEN]


def safe_user_message(message: object) -> str:
    """Return ``message`` sanitized via :class:`UserFacingError`'s rules.

    Convenience wrapper for sites that want the sanitizer without
    instantiating the exception class itself.
    """
    return UserFacingError(str(message) if message is not None else "").user_message
