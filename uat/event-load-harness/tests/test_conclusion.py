"""derive_conclusion turns a run's evidence into an honest supported-concurrency statement."""

from event_load_harness.config import RunConfig
from event_load_harness.report import derive_conclusion
from event_load_harness.results import RouteResult
from event_load_harness.stats import Aggregator


def _config(concurrency=100):
    return RunConfig.from_dict(
        {
            "target_url": "https://dev.example.com",
            "environment": "dev",
            "profile": "portal-core",
            "concurrency": concurrency,
            "ramp_seconds": 0,
            "duration_seconds": 10,
            "actor_source": "dev-login",
            "metric_source": "client-only",
            "report_path": "out/e.md",
            "confirm_host": "dev.example.com",
        }
    )


def _summary(results):
    agg = Aggregator()
    for r in results:
        agg.add(r)
    return agg.summary()


def test_no_saturation_reports_at_least_target():
    summary = _summary([RouteResult("page:dashboard", "http", ok=True, status_code=200, latency_ms=5.0)])
    c = derive_conclusion(_config(100), summary)
    assert "at least 100" in c.supported_concurrency
    assert "no saturation" in c.limiting_factor.lower()
    assert "#910" in c.sizing_implication


def test_terminal_ws_unavailable_is_the_limiting_factor():
    summary = _summary(
        [
            RouteResult(
                "ws:terminal",
                "ws",
                ok=False,
                status_code=None,
                latency_ms=5.0,
                ws_opened=True,
                ws_dropped=True,
                close_code=4503,
                error_category="service_unavailable",
            ),
        ]
    )
    c = derive_conclusion(_config(100), summary)
    assert "below 100" in c.supported_concurrency
    assert "websocket" in c.limiting_factor.lower() or "terminal" in c.limiting_factor.lower()


def test_server_errors_flagged_as_limiting_factor():
    summary = _summary(
        [
            RouteResult(
                "page:dashboard", "http", ok=False, status_code=500, latency_ms=5.0, error_category="server_error"
            ),
        ]
    )
    c = derive_conclusion(_config(50), summary)
    assert "5xx" in c.limiting_factor or "server" in c.limiting_factor.lower()
