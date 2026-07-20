"""The common result record produced by every route executor.

Kept dependency-free so both the route layer (which produces results) and the
stats layer (which aggregates them) can import it without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteResult:
    """One observation from driving a single route once.

    ``latency_ms`` is the request round-trip for HTTP routes, or the
    time-to-open for websocket routes. Secret-bearing material (cookies, signed
    URLs, response bodies) is never stored here: only low-cardinality labels and
    aggregate-friendly fields.
    """

    route_class: str
    kind: str  # "http" | "ws"
    ok: bool
    status_code: int | None
    latency_ms: float
    error_category: str | None = None
    ws_opened: bool = False
    ws_dropped: bool = False
    close_code: int | None = None
    reconnects: int = 0
