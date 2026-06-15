"""Latency percentiles and per-route aggregation must be correct.

A single average latency hides the tail; the preflight requires per-route
p50/p95/p99 plus error and websocket close-code distributions.
"""

import pytest

from event_load_harness.results import RouteResult
from event_load_harness.stats import Aggregator, percentile


def test_percentile_nearest_rank_basics():
    values = [float(n) for n in range(1, 101)]  # 1..100
    assert percentile(values, 50) == pytest.approx(50, abs=1)
    assert percentile(values, 95) == pytest.approx(95, abs=1)
    assert percentile(values, 99) == pytest.approx(99, abs=1)


def test_percentile_single_value():
    assert percentile([7.0], 95) == 7.0


def test_percentile_empty_is_none():
    assert percentile([], 95) is None


def test_aggregator_http_counts_and_percentiles():
    agg = Aggregator()
    for i in range(10):
        agg.add(RouteResult("page:dashboard", "http", ok=True, status_code=200, latency_ms=float(i + 1)))
    agg.add(
        RouteResult(
            "page:dashboard", "http", ok=False, status_code=503, latency_ms=99.0, error_category="service_unavailable"
        )
    )
    summary = agg.summary()
    page = summary["routes"]["page:dashboard"]
    assert page["requests"] == 11
    assert page["ok"] == 10
    assert page["errors"] == 1
    assert page["errors_by_status"]["503"] == 1
    assert page["errors_by_category"]["service_unavailable"] == 1
    assert page["latency_ms"]["p95"] is not None


def test_aggregator_websocket_close_codes_and_reconnects():
    agg = Aggregator()
    agg.add(
        RouteResult("ws:terminal", "ws", ok=True, status_code=None, latency_ms=5.0, ws_opened=True, close_code=1000)
    )
    agg.add(
        RouteResult(
            "ws:terminal",
            "ws",
            ok=False,
            status_code=None,
            latency_ms=5.0,
            ws_opened=True,
            ws_dropped=True,
            close_code=4503,
            reconnects=3,
            error_category="service_unavailable",
        )
    )
    summary = agg.summary()
    ws = summary["routes"]["ws:terminal"]
    assert ws["ws_opened"] == 2
    assert ws["ws_dropped"] == 1
    assert ws["reconnects"] == 3
    assert ws["close_codes"]["NORMAL"] == 1
    assert ws["close_codes"]["SERVICE_UNAVAILABLE"] == 1


def test_aggregator_totals_roll_up_across_routes():
    agg = Aggregator()
    agg.add(RouteResult("page:home", "http", ok=True, status_code=200, latency_ms=1.0))
    agg.add(
        RouteResult(
            "ws:range-status",
            "ws",
            ok=False,
            status_code=None,
            latency_ms=1.0,
            ws_opened=True,
            ws_dropped=True,
            close_code=4001,
        )
    )
    summary = agg.summary()
    assert summary["totals"]["requests"] == 2
    assert summary["totals"]["ok"] == 1
    assert summary["totals"]["errors"] == 1
