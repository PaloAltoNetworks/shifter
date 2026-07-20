"""Pure-Python latency percentiles and per-route aggregation.

No numpy/pandas: the aggregation is simple and keeping deps narrow matters for a
tool operators run from a laptop. The summary intentionally reports per-route
p50/p95/p99 plus error and websocket close-code distributions rather than a
single average, which hides the tail the event-baseline question cares about.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from event_load_harness.closecodes import close_code_label
from event_load_harness.results import RouteResult


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile of ``values`` at ``q`` in [0, 100].

    Returns ``None`` for an empty sample. Nearest-rank (rather than
    interpolation) keeps the result a value actually observed, which reads
    honestly in a latency report.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(1, math.ceil(q / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


class _RouteAccumulator:
    def __init__(self) -> None:
        self.requests = 0
        self.ok = 0
        self.errors = 0
        self.latencies: list[float] = []
        self.errors_by_status: dict[str, int] = defaultdict(int)
        self.errors_by_category: dict[str, int] = defaultdict(int)
        self.ws_opened = 0
        self.ws_dropped = 0
        self.reconnects = 0
        self.close_codes: dict[str, int] = defaultdict(int)
        self.has_ws = False

    def add(self, r: RouteResult) -> None:
        self.requests += 1
        self.latencies.append(r.latency_ms)
        if r.ok:
            self.ok += 1
        else:
            self.errors += 1
            if r.status_code is not None:
                self.errors_by_status[str(r.status_code)] += 1
            if r.error_category:
                self.errors_by_category[r.error_category] += 1
        if r.kind == "ws":
            self.has_ws = True
            if r.ws_opened:
                self.ws_opened += 1
            if r.ws_dropped:
                self.ws_dropped += 1
            self.reconnects += r.reconnects
            self.close_codes[close_code_label(r.close_code)] += 1

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "requests": self.requests,
            "ok": self.ok,
            "errors": self.errors,
            "latency_ms": {
                "p50": percentile(self.latencies, 50),
                "p95": percentile(self.latencies, 95),
                "p99": percentile(self.latencies, 99),
            },
            "errors_by_status": dict(self.errors_by_status),
            "errors_by_category": dict(self.errors_by_category),
        }
        if self.has_ws:
            out["ws_opened"] = self.ws_opened
            out["ws_dropped"] = self.ws_dropped
            out["reconnects"] = self.reconnects
            out["close_codes"] = dict(self.close_codes)
        return out


class Aggregator:
    """Collects RouteResults and renders a per-route + total summary dict."""

    def __init__(self) -> None:
        self._routes: dict[str, _RouteAccumulator] = defaultdict(_RouteAccumulator)

    def add(self, result: RouteResult) -> None:
        self._routes[result.route_class].add(result)

    def summary(self) -> dict[str, Any]:
        routes = {name: acc.summary() for name, acc in sorted(self._routes.items())}
        totals = {
            "requests": sum(a.requests for a in self._routes.values()),
            "ok": sum(a.ok for a in self._routes.values()),
            "errors": sum(a.errors for a in self._routes.values()),
        }
        return {"routes": routes, "totals": totals}
