"""Gunicorn worker class with an explicit WebSocket keepalive (#931).

``entrypoint.sh`` serves the portal with Gunicorn managing Uvicorn ASGI
workers. The portal's primary workload is long-lived WebSocket traffic
(terminal SSH, range-status, notification sockets, and the Guacamole
browser tunnel). The shared AWS ALB closes any connection that sits idle
longer than its ``idle_timeout``; the only thing that keeps an otherwise
quiet terminal alive is the Uvicorn server sending protocol-level PING
frames at ``ws_ping_interval``, which the ALB counts as activity.

The architecture preflight
(``docs/architecture/aws-long-lived-connection-drain-preflight-931.md``)
forbids *assuming* Uvicorn's default ping is active in the built
Gunicorn-worker path. The bare ``uvicorn_worker.UvicornWorker`` ships
``CONFIG_KWARGS = {"loop": "auto", "http": "auto"}`` and leaves the ping
settings to whatever Uvicorn's ``Config`` defaults happen to be, which is
exactly the implicit reliance the preflight rules out. This subclass pins
the interval and timeout explicitly so the keepalive is a deliberate,
env-owned setting sized below the ALB ``idle_timeout`` rather than an
inherited default.

The values are non-secret process-manager timings. They are read once at
class-definition time (Gunicorn imports the worker class at master boot,
after ``entrypoint.sh`` has exported any overrides) and fail the master
boot loudly if they are non-numeric or non-positive, rather than silently
disabling the keepalive.
"""

from __future__ import annotations

import os

from uvicorn_worker import UvicornWorker

# Default keepalive interval/timeout in seconds. Sized well below the ALB
# idle_timeout (default 300s, see modules/portal/alb) so an idle terminal's
# connection is refreshed many times over before the load balancer would
# reap it.
_DEFAULT_WS_PING_INTERVAL = 20.0
_DEFAULT_WS_PING_TIMEOUT = 20.0


def _positive_float_env(name: str, default: float) -> float:
    """Read a positive float from the environment, failing loud on bad input.

    An empty/unset variable yields ``default``. A value that does not parse as
    a number, or that is not strictly positive, raises ``ValueError`` so the
    Gunicorn master aborts at boot instead of starting workers with a disabled
    or nonsensical keepalive.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number of seconds, got {value!r}")
    return value


class ShifterUvicornWorker(UvicornWorker):
    """Uvicorn worker that pins the WebSocket keepalive for the portal."""

    CONFIG_KWARGS = {
        **UvicornWorker.CONFIG_KWARGS,
        "ws_ping_interval": _positive_float_env("PORTAL_WEB_WS_PING_INTERVAL", _DEFAULT_WS_PING_INTERVAL),
        "ws_ping_timeout": _positive_float_env("PORTAL_WEB_WS_PING_TIMEOUT", _DEFAULT_WS_PING_TIMEOUT),
    }
