"""The pool server's only HTTP client.

It opens ``http:`` and ``https:`` URLs only and never follows a redirect, so no
caller can be steered to a local file, another scheme, or another host. It
ignores proxy environment variables.
"""

from __future__ import annotations

import urllib.request


def closed_opener() -> urllib.request.OpenerDirector:
    """Return an opener with HTTP(S) handlers and error processing; other schemes raise."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPHandler(),
        # The default context verifies certificates and host names.
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
        # Without this, an unsupported scheme silently returns None.
        urllib.request.UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


OPENER = closed_opener()
