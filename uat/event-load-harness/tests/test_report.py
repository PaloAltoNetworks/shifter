"""The envelope report must cover the preflight Evidence Bar, label gaps, and stay sanitized."""

import pytest

from event_load_harness.config import RunConfig
from event_load_harness.metrics.client_only import ClientOnlyAdapter
from event_load_harness.report import (
    Conclusion,
    DeploymentShape,
    ReportError,
    RunMeta,
    render_envelope,
)
from event_load_harness.results import RouteResult
from event_load_harness.stats import Aggregator


def _config(**kw):
    data = {
        "target_url": "https://dev.example.com",
        "environment": "dev",
        "profile": "portal-core",
        "concurrency": 50,
        "ramp_seconds": 30,
        "duration_seconds": 120,
        "actor_source": "manifest",
        "actor_manifest_path": "/tmp/a.toml",  # noqa: S108
        "metric_source": "client-only",
        "report_path": "out/envelope.md",
        "confirm_host": "dev.example.com",
    }
    data.update(kw)
    return RunConfig.from_dict(data)


def _stats():
    agg = Aggregator()
    for i in range(20):
        agg.add(RouteResult("page:dashboard", "http", ok=True, status_code=200, latency_ms=float(i + 1)))
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
            reconnects=2,
            error_category="service_unavailable",
        )
    )
    return agg.summary()


def _render(**overrides):
    args = {
        "config": _config(),
        "run_meta": RunMeta(started_at="2026-06-14T00:00:00Z", ended_at="2026-06-14T00:05:00Z", git_sha="abc1234"),
        "deployment": DeploymentShape(instances="1 EC2 (ASG 1/1/1)", process_model="single Daphne process"),
        "stats_summary": _stats(),
        "metrics": ClientOnlyAdapter().collect("2026-06-14T00:00:00Z", "2026-06-14T00:05:00Z"),
        "conclusion": Conclusion(
            supported_concurrency="~150 concurrent participants",
            margin="25% headroom",
            limiting_factor="terminal websocket FDs on the single Daphne process",
            sizing_implication="confirms #910 needs >1 portal instance for 300+ participants",
            first_mover_signal="ws:terminal SERVICE_UNAVAILABLE close codes before HTTP errors",
        ),
    }
    args.update(overrides)
    return render_envelope(**args)


def test_envelope_includes_run_parameters_and_target():
    config = _config()
    md = _render(config=config)
    # Assert on the config-derived value, not a hardcoded URL literal: the report
    # must surface whatever target the run actually used.
    assert config.target_url in md
    assert config.profile in md
    assert str(config.concurrency) in md
    assert "abc1234" in md  # git sha


def test_envelope_includes_per_route_tail_latency():
    md = _render()
    assert "p95" in md
    assert "p99" in md
    assert "page:dashboard" in md


def test_envelope_includes_websocket_close_codes_and_reconnects():
    md = _render()
    assert "SERVICE_UNAVAILABLE" in md
    assert "ws:terminal" in md
    assert "reconnect" in md.lower()


def test_envelope_lists_provider_gaps_explicitly():
    md = _render()
    assert "gap" in md.lower()
    assert "RDS" in md  # a named missing signal


def test_envelope_states_supported_concurrency_conclusion():
    md = _render()
    assert "concurrent participants" in md
    assert "limiting factor" in md.lower()
    assert "#910" in md


def test_unknown_deployment_fields_render_as_unknown_not_blank():
    md = _render(deployment=DeploymentShape())
    assert "unknown" in md.lower()


def test_render_refuses_to_emit_secret_material():
    # Defense in depth: if a caller-supplied field smuggled a secret, the
    # renderer's sanitization scan refuses rather than writing it to disk.
    leaky = DeploymentShape(redis_posture="auth via sessionid=supersecretcookievalue")
    with pytest.raises(ReportError, match=r"sanitiz|secret"):
        _render(deployment=leaky)
