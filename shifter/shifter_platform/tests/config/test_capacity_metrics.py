"""Tests for the portal web capacity metrics emitter (Shifter/PortalCapacity, #940).

These cover the process-local in-flight accounting, the pure snapshot/payload
helpers, and the fail-soft emitter loop. The emitter is exercised without boto3
or a network: a fake CloudWatch client records the call, and the failure path
asserts the loop never raises into the request-serving process.
"""

from __future__ import annotations

import asyncio

import pytest

from config import capacity_metrics
from config.middleware import RequestInFlightMiddleware


@pytest.fixture(autouse=True)
def _reset_counter():
    """Each test starts from a clean in-flight counter for deterministic deltas."""
    capacity_metrics.inflight_requests.reset()
    yield
    capacity_metrics.inflight_requests.reset()


class _FakeCloudWatch:
    """Records put_metric_data calls; optionally raises to drive the fail path."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._raises = raises

    def put_metric_data(self, **kwargs):
        if self._raises is not None:
            raise self._raises
        self.calls.append(kwargs)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}


def test_inflight_counter_increment_decrement_floors_at_zero():
    counter = capacity_metrics.InFlightCounter()
    assert counter.current() == 0
    counter.increment()
    counter.increment()
    assert counter.current() == 2
    counter.decrement()
    assert counter.current() == 1
    # Defensive: an extra decrement never drives the gauge negative.
    counter.decrement()
    counter.decrement()
    assert counter.current() == 0


def test_compute_snapshot_ratios_and_denominators():
    snap = capacity_metrics.compute_snapshot(
        in_flight=3,
        terminal_active=50,
        soft_concurrency=6,
        terminal_max_sessions=200,
    )
    assert snap.in_flight_requests == 3
    assert snap.worker_busy_ratio == pytest.approx(0.5)
    assert snap.terminal_active_sessions == 50
    assert snap.terminal_session_utilization == pytest.approx(0.25)


def test_compute_snapshot_zero_denominator_is_safe():
    # A misconfigured (<=0) denominator must not divide-by-zero; ratio is 0.0.
    snap = capacity_metrics.compute_snapshot(
        in_flight=5,
        terminal_active=5,
        soft_concurrency=0,
        terminal_max_sessions=0,
    )
    assert snap.worker_busy_ratio == 0.0
    assert snap.terminal_session_utilization == 0.0


def test_build_metric_data_is_low_cardinality_and_complete():
    snap = capacity_metrics.compute_snapshot(
        in_flight=4,
        terminal_active=10,
        soft_concurrency=4,
        terminal_max_sessions=200,
    )
    data = capacity_metrics.build_metric_data(snap, "dev-portal")
    names = {m["MetricName"] for m in data}
    assert names == {
        "WorkerInFlightRequests",
        "WorkerBusyRatio",
        "TerminalActiveSessions",
        "TerminalSessionUtilization",
    }
    # Only the NamePrefix dimension is allowed: no user/session/path/instance keys.
    for metric in data:
        assert metric["Dimensions"] == [{"Name": "NamePrefix", "Value": "dev-portal"}]
        assert isinstance(metric["Value"], float)
        assert metric["Unit"] in {"Count", "None", "Percent"}


def test_emit_once_publishes_to_portal_capacity_namespace():
    client = _FakeCloudWatch()
    emitter = capacity_metrics.PortalCapacityEmitter(
        client=client,
        name_prefix="dev-portal",
        interval_seconds=60,
        soft_concurrency=6,
        terminal_max_sessions=200,
        collector=lambda sc, tms: capacity_metrics.compute_snapshot(
            in_flight=6, terminal_active=100, soft_concurrency=sc, terminal_max_sessions=tms
        ),
    )
    assert emitter.emit_once() is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Namespace"] == capacity_metrics.NAMESPACE == "Shifter/PortalCapacity"
    busy = next(m for m in call["MetricData"] if m["MetricName"] == "WorkerBusyRatio")
    assert busy["Value"] == pytest.approx(1.0)


def test_emit_once_is_fail_soft_when_client_raises():
    client = _FakeCloudWatch(raises=RuntimeError("throttled: secret-bearing detail"))
    emitter = capacity_metrics.PortalCapacityEmitter(
        client=client,
        name_prefix="dev-portal",
        interval_seconds=60,
        soft_concurrency=6,
        terminal_max_sessions=200,
        collector=lambda sc, tms: capacity_metrics.compute_snapshot(
            in_flight=1, terminal_active=1, soft_concurrency=sc, terminal_max_sessions=tms
        ),
    )
    # Must swallow the error so a CloudWatch outage never breaks request serving.
    assert emitter.emit_once() is False


def test_inflight_middleware_sync_brackets_get_response():
    seen = {}

    def get_response(request):
        seen["during"] = capacity_metrics.inflight_requests.current()
        return "response"

    middleware = RequestInFlightMiddleware(get_response)
    before = capacity_metrics.inflight_requests.current()
    result = middleware(object())
    assert result == "response"
    assert seen["during"] == before + 1
    assert capacity_metrics.inflight_requests.current() == before


def test_inflight_middleware_async_brackets_get_response():
    seen = {}

    async def get_response(request):
        seen["during"] = capacity_metrics.inflight_requests.current()
        return "response"

    middleware = RequestInFlightMiddleware(get_response)
    before = capacity_metrics.inflight_requests.current()
    result = asyncio.run(middleware(object()))
    assert result == "response"
    assert seen["during"] == before + 1
    assert capacity_metrics.inflight_requests.current() == before


def test_inflight_middleware_decrements_even_when_get_response_raises():
    def get_response(request):
        raise ValueError("boom")

    middleware = RequestInFlightMiddleware(get_response)
    before = capacity_metrics.inflight_requests.current()
    with pytest.raises(ValueError):
        middleware(object())
    assert capacity_metrics.inflight_requests.current() == before


def test_build_emitter_disabled_returns_none_and_skips_client():
    factory_called = []
    emitter = capacity_metrics.build_emitter_from_config(
        enabled=False,
        name_prefix="dev-portal",
        interval_seconds=60,
        soft_concurrency=4,
        terminal_max_sessions=200,
        client_factory=lambda: factory_called.append(True),
    )
    assert emitter is None
    assert factory_called == []  # never even constructs a client when disabled


def test_build_emitter_missing_name_prefix_returns_none():
    # Enabled but no NamePrefix: the alarms/dashboard could not match the series,
    # so refuse to start rather than emit an unlabelled (cross-environment) metric.
    emitter = capacity_metrics.build_emitter_from_config(
        enabled=True,
        name_prefix="",
        interval_seconds=60,
        soft_concurrency=4,
        terminal_max_sessions=200,
        client_factory=lambda: _FakeCloudWatch(),
    )
    assert emitter is None


def test_build_emitter_client_factory_failure_is_soft():
    def boom():
        raise RuntimeError("no credentials")

    emitter = capacity_metrics.build_emitter_from_config(
        enabled=True,
        name_prefix="dev-portal",
        interval_seconds=60,
        soft_concurrency=4,
        terminal_max_sessions=200,
        client_factory=boom,
    )
    assert emitter is None  # a boto3/credential failure must not crash worker boot


def test_build_emitter_enabled_starts_thread():
    client = _FakeCloudWatch()
    emitter = capacity_metrics.build_emitter_from_config(
        enabled=True,
        name_prefix="dev-portal",
        interval_seconds=3600,  # long: the immediate first emit is enough for the test
        soft_concurrency=4,
        terminal_max_sessions=200,
        client_factory=lambda: client,
        collector=lambda sc, tms: capacity_metrics.compute_snapshot(
            in_flight=0, terminal_active=0, soft_concurrency=sc, terminal_max_sessions=tms
        ),
    )
    assert emitter is not None
    try:
        # The first sample is emitted immediately on thread start.
        deadline = 2.0
        waited = 0.0
        while not client.calls and waited < deadline:
            import time

            time.sleep(0.02)
            waited += 0.02
        assert client.calls, "emitter thread did not publish an initial sample"
        assert client.calls[0]["Namespace"] == capacity_metrics.NAMESPACE
    finally:
        emitter.stop()
