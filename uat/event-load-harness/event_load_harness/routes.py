"""Route contracts and the live route executor.

Two layers:

* **Pure contract layer** (``HTTP_ROUTES``, ``WS_ROUTES``, ``http_method_and_path``,
  ``classify_http``) - the route->endpoint map and the HTTP error taxonomy.
  Deterministic and unit-tested; pins the contract against the real portal urls.
* **Live executor** (``LiveRouteExecutor``) - drives the *real* deployed
  endpoints over httpx/websockets and returns a ``RouteResult``. This layer
  talks to a deployed environment, so it is exercised by operator runs rather
  than CI (the preflight forbids mocking the app to satisfy load).

Endpoint provenance (shifter/shifter_platform):
  ``ctf/urls.py``           -> /ctf/, /ctf/scoreboard/, /ctf/api/range/status/
  ``mission_control/urls.py`` -> /mission-control/api/guacamole/rdp-url/
  ``mission_control/routing.py`` -> ws/terminal/<uuid>/, ws/range-status/<id>/
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from event_load_harness.auth import Actor
from event_load_harness.closecodes import close_code_label
from event_load_harness.results import RouteResult

# Active HTTP route classes -> (method, path). Paths are app-relative.
HTTP_ROUTES: dict[str, tuple[str, str]] = {
    "page:dashboard": ("GET", "/ctf/"),
    "page:ctf-event": ("GET", "/ctf/event/"),
    "page:scoreboard": ("GET", "/ctf/scoreboard/"),
    "range:status-poll": ("GET", "/ctf/api/range/status/"),
    "guacamole:bootstrap": ("POST", "/mission-control/api/guacamole/rdp-url/"),
}

# Active websocket route classes -> path template (the id is filled per-actor).
WS_ROUTES: dict[str, str] = {
    "ws:terminal": "/ws/terminal/{instance_uuid}/",
    "ws:range-status": "/ws/range-status/{request_id}/",
}


def http_method_and_path(route_class: str) -> tuple[str, str]:
    """Return ``(method, path)`` for an active HTTP route class. Raises KeyError if unknown."""
    return HTTP_ROUTES[route_class]


def classify_http(status_code: int) -> tuple[bool, str | None]:
    """Map an HTTP status to ``(ok, error_category)`` with a low-cardinality taxonomy."""
    if status_code < 400:
        return True, None
    if status_code == 429:
        return False, "rate_limited"
    if status_code == 503:
        return False, "service_unavailable"
    if status_code >= 500:
        return False, "server_error"
    return False, "client_error"


# --------------------------------------------------------------------------- #
# Live executor (operator-run; not covered by CI tests).                      #
# --------------------------------------------------------------------------- #


class LiveRouteExecutor:
    """Drives real portal endpoints for a set of authenticated actors.

    ``setup`` authenticates each actor and discovers per-actor target ids
    (instance uuid, range request id). ``__call__`` matches the runner's
    executor contract: ``async (actor, route_class) -> RouteResult``. A route
    with no discovered target returns an honest ``no_target`` error result
    rather than raising, so one un-provisioned actor never aborts the run.
    """

    def __init__(self, base_url: str, *, ws_recv_timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_recv_timeout = ws_recv_timeout
        self._clients: dict[str, Any] = {}
        self._targets: dict[str, dict[str, str]] = {}

    async def setup(self, actors: list[Actor], authenticator) -> None:
        """Authenticate every actor and discover their range targets.

        ``authenticator`` is an async callable ``(base_url, actor) -> httpx.AsyncClient``
        injected by the caller (see ``auth_http``), so this module does not hard-code
        an auth exchange and stays testable.
        """
        for actor in actors:
            client = await authenticator(self.base_url, actor)
            self._clients[actor.label] = client
            self._targets[actor.label] = await self._discover_targets(client)

    async def _discover_targets(self, client) -> dict[str, str]:
        """Best-effort discovery of an actor's instance uuid + range request id."""
        targets: dict[str, str] = {}
        try:
            resp = await client.get("/mission-control/api/range/")
            if resp.status_code < 400:
                data = resp.json()
                rid = data.get("request_id") or data.get("range", {}).get("request_id")
                if rid:
                    targets["request_id"] = str(rid)
                instances = data.get("instances") or data.get("range", {}).get("instances") or []
                if instances:
                    uuid = instances[0].get("uuid") or instances[0].get("instance_uuid")
                    if uuid:
                        targets["instance_uuid"] = str(uuid)
        except Exception:
            return targets
        return targets

    async def __call__(self, actor: Actor, route_class: str) -> RouteResult:
        if route_class in HTTP_ROUTES:
            return await self._http(actor, route_class)
        if route_class in WS_ROUTES:
            return await self._ws(actor, route_class)
        raise KeyError(f"no executor for route class {route_class!r}")

    async def _http(self, actor: Actor, route_class: str) -> RouteResult:
        client = self._clients[actor.label]
        method, path = http_method_and_path(route_class)
        body = self._http_body(actor, route_class)
        if body is _NO_TARGET:
            return RouteResult(
                route_class, "http", ok=False, status_code=None, latency_ms=0.0, error_category="no_target"
            )
        start = time.monotonic()
        try:
            resp = await client.request(method, path, **({"json": body} if body else {}))
        except Exception:
            elapsed = (time.monotonic() - start) * 1000.0
            return RouteResult(
                route_class, "http", ok=False, status_code=None, latency_ms=elapsed, error_category="transport_error"
            )
        elapsed = (time.monotonic() - start) * 1000.0
        ok, category = classify_http(resp.status_code)
        return RouteResult(
            route_class, "http", ok=ok, status_code=resp.status_code, latency_ms=elapsed, error_category=category
        )

    def _http_body(self, actor: Actor, route_class: str):
        if route_class == "guacamole:bootstrap":
            rid = self._targets.get(actor.label, {}).get("request_id")
            if not rid:
                return _NO_TARGET
            return {"request_id": rid}
        return None

    async def _ws(self, actor: Actor, route_class: str) -> RouteResult:
        import websockets  # local import keeps the contract layer import-light

        targets = self._targets.get(actor.label, {})
        path_tmpl = WS_ROUTES[route_class]
        key = "instance_uuid" if "{instance_uuid}" in path_tmpl else "request_id"
        ident = targets.get(key)
        if not ident:
            return RouteResult(
                route_class, "ws", ok=False, status_code=None, latency_ms=0.0, error_category="no_target"
            )
        url = self._ws_url(path_tmpl.format(**{key: ident}))
        client = self._clients[actor.label]
        headers = ws_handshake_headers(client, self.base_url)
        start = time.monotonic()
        opened = False
        try:
            async with websockets.connect(url, additional_headers=headers, open_timeout=self.ws_recv_timeout) as ws:
                opened = True
                open_ms = (time.monotonic() - start) * 1000.0
                server_close = await _probe_recv(ws, self.ws_recv_timeout)
                if server_close is not None:
                    # The server closed during the probe window. Record its actual
                    # close code; a non-normal code (e.g. SERVICE_UNAVAILABLE) is a
                    # drop, never a swallowed NORMAL success.
                    ok, category = ws_close_result(server_close)
                    return RouteResult(
                        route_class,
                        "ws",
                        ok=ok,
                        status_code=None,
                        latency_ms=open_ms,
                        ws_opened=True,
                        ws_dropped=not ok,
                        close_code=server_close,
                        error_category=category,
                    )
                await ws.close(code=1000)
            return RouteResult(
                route_class, "ws", ok=True, status_code=None, latency_ms=open_ms, ws_opened=True, close_code=1000
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000.0
            code = _extract_close_code(exc)
            ok, category = ws_close_result(code) if code is not None else (False, "ws_drop")
            return RouteResult(
                route_class,
                "ws",
                ok=ok,
                status_code=None,
                latency_ms=elapsed,
                ws_opened=opened,
                ws_dropped=opened and not ok,
                close_code=code,
                error_category=category,
            )

    def _ws_url(self, path: str) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[1]
        return f"{scheme}://{host}{path}"

    async def aclose(self) -> None:
        for client in self._clients.values():
            with contextlib.suppress(Exception):
                await client.aclose()


_NO_TARGET = object()

_CLEAN_CLOSE_CODES = (1000, 1001)  # NORMAL, GOING_AWAY


def ws_close_result(code: int | None) -> tuple[bool, str | None]:
    """Map a websocket close code to ``(ok, error_category)``.

    Only a clean close (NORMAL / GOING_AWAY) is success; any other code, including
    the application codes SERVICE_UNAVAILABLE / SSH_CONNECTION_FAILED, is a drop.
    """
    if code in _CLEAN_CLOSE_CODES:
        return True, None
    return False, close_code_label(code).lower()


def _extract_close_code(exc: Exception) -> int | None:
    """Best-effort close-code extraction from a websockets ConnectionClosed, across versions."""
    rcvd = getattr(exc, "rcvd", None)
    if rcvd is not None and getattr(rcvd, "code", None) is not None:
        return rcvd.code
    return getattr(exc, "code", None)


async def _probe_recv(ws, timeout: float) -> int | None:
    """Wait for one frame. Return None on a frame or a no-frame timeout (both benign);
    return the server's close code if the server closed during the window."""
    import asyncio

    import websockets

    try:
        await asyncio.wait_for(ws.recv(), timeout=timeout)
        return None
    except TimeoutError:
        return None
    except websockets.ConnectionClosed as exc:
        return _extract_close_code(exc)


def _cookie_header(client) -> list[tuple[str, str]]:
    """Build a Cookie header from an httpx client's cookie jar for the ws handshake."""
    cookies = getattr(client, "cookies", None)
    if not cookies:
        return []
    pairs = "; ".join(f"{name}={value}" for name, value in cookies.items())
    return [("Cookie", pairs)] if pairs else []


def ws_handshake_headers(client, origin: str) -> list[tuple[str, str]]:
    """Headers for the websocket handshake: session cookies plus the browser Origin.

    Channels' ``AllowedHostsOriginValidator`` is part of the real contract under
    test; a browser sends ``Origin``, so the harness must too, or the handshake is
    rejected for the wrong reason and the measurement stops matching the browser path.
    """
    headers = _cookie_header(client)
    headers.append(("Origin", origin))
    return headers
