"""Strict shared-service event gate tests (#1816)."""

from __future__ import annotations

import copy

import pytest

from event_load_harness.capacity_gate import CapacityGateBudget, evaluate_capacity_gate
from event_load_harness.metrics.base import MetricsResult, MetricValue


def _metric(name: str, value: float, unit: str = "count") -> MetricValue:
    return MetricValue(name=name, value=value, unit=unit, provenance="test")


def _metrics() -> MetricsResult:
    values = {
        "portal.pod_restart_delta": _metric("portal.pod_restart_delta", 0),
        "guacamole_client.pod_restart_delta": _metric("guacamole_client.pod_restart_delta", 0),
        "guacd.pod_restart_delta": _metric("guacd.pod_restart_delta", 0),
        "guacd.ready_replicas": _metric("guacd.ready_replicas", 2),
        "guacd.cpu_utilization_pct": _metric("guacd.cpu_utilization_pct", 55, "percent"),
        "redis.connection_utilization_pct": _metric("redis.connection_utilization_pct", 20, "percent"),
        "redis.memory_utilization_pct": _metric("redis.memory_utilization_pct", 30, "percent"),
        "redis.eviction_delta": _metric("redis.eviction_delta", 0),
        "redis.rejected_connection_delta": _metric("redis.rejected_connection_delta", 0),
        "cloud_sql.connection_utilization_pct": _metric("cloud_sql.connection_utilization_pct", 25, "percent"),
        "cloud_sql.connection_error_delta": _metric("cloud_sql.connection_error_delta", 0),
        "cloud_sql.cpu_utilization_pct": _metric("cloud_sql.cpu_utilization_pct", 40, "percent"),
        "load_balancer.backend_latency_p95_ms": _metric("load_balancer.backend_latency_p95_ms", 500, "ms"),
        "load_balancer.backend_5xx_delta": _metric("load_balancer.backend_5xx_delta", 0),
        "load_balancer.timeout_delta": _metric("load_balancer.timeout_delta", 0),
        "load_balancer.unhealthy_backend_count": _metric("load_balancer.unhealthy_backend_count", 0),
        "load_balancer.dropped_connection_delta": _metric("load_balancer.dropped_connection_delta", 0),
    }
    return MetricsResult("gcp", "start", "end", metrics=values)


def _summary() -> dict:
    return {
        "routes": {
            "guacamole:session-hold": {
                "requests": 30,
                "ok": 30,
                "errors": 0,
                "latency_ms": {"p50": 900, "p95": 1500, "p99": 1800},
                "ws_opened": 30,
                "ws_dropped": 0,
                "display_synchronized": 30,
                "held_seconds_min": 120,
            }
        },
        "totals": {"requests": 30, "ok": 30, "errors": 0},
    }


def test_strict_gate_passes_complete_healthy_evidence():
    budget = CapacityGateBudget.p30()
    verdict = evaluate_capacity_gate(budget, _summary(), _metrics())

    assert budget.concurrency == 30
    assert budget.required_guacd_replicas == 2
    assert budget.cloud_sql_max_utilization_pct == 75
    assert verdict.passed is True
    assert verdict.failures == ()


def test_strict_gate_fails_on_drop_saturation_or_missing_metric():
    summary = _summary()
    summary["routes"]["guacamole:session-hold"]["ws_dropped"] = 1
    metrics = _metrics()
    metrics.metrics["redis.connection_utilization_pct"] = _metric("redis.connection_utilization_pct", 95, "percent")
    metrics.metrics.pop("cloud_sql.connection_error_delta")

    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), summary, metrics)

    assert verdict.passed is False
    assert any("tunnel drop" in failure for failure in verdict.failures)
    assert any("Redis connection utilization" in failure for failure in verdict.failures)
    assert any("cloud_sql.connection_error_delta" in failure for failure in verdict.failures)


def test_strict_gate_rejects_missing_route_evidence():
    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), {"routes": {}}, _metrics())

    assert "missing guacamole:session-hold route evidence" in verdict.failures


@pytest.mark.parametrize(
    ("field", "value", "expected_failure"),
    [
        ("requests", 29, "expected 30 concurrent tunnel attempts"),
        ("ok", 29, "every participant tunnel must succeed"),
        ("errors", 1, "every participant tunnel must succeed"),
        ("display_synchronized", 29, "every participant tunnel must reach display synchronization"),
        ("ws_dropped", 1, "unexpected tunnel drop during sustained hold"),
        ("held_seconds_min", 119, "every tunnel must remain held for at least 120s"),
    ],
)
def test_strict_gate_rejects_each_invalid_route_counter(field, value, expected_failure):
    summary = copy.deepcopy(_summary())
    summary["routes"]["guacamole:session-hold"][field] = value

    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), summary, _metrics())

    assert expected_failure in verdict.failures


def test_strict_gate_requires_bootstrap_latency_percentiles():
    summary = copy.deepcopy(_summary())
    summary["routes"]["guacamole:session-hold"].pop("latency_ms")

    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), summary, _metrics())

    assert "missing bootstrap latency percentiles" in verdict.failures


@pytest.mark.parametrize(
    ("percentile", "value", "expected_failure"),
    [
        ("p95", 5001, "bootstrap p95 exceeded the authored budget"),
        ("p99", 8001, "bootstrap p99 exceeded the authored budget"),
    ],
)
def test_strict_gate_rejects_each_bootstrap_latency_budget(percentile, value, expected_failure):
    summary = copy.deepcopy(_summary())
    summary["routes"]["guacamole:session-hold"]["latency_ms"][percentile] = value

    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), summary, _metrics())

    assert expected_failure in verdict.failures


@pytest.mark.parametrize(
    ("name", "expected_label"),
    [
        ("portal.pod_restart_delta", "portal pod restart delta"),
        ("guacamole_client.pod_restart_delta", "guacamole-client pod restart delta"),
        ("guacd.pod_restart_delta", "guacd pod restart delta"),
        ("redis.eviction_delta", "Redis eviction delta"),
        ("redis.rejected_connection_delta", "Redis rejected-connection delta"),
        ("cloud_sql.connection_error_delta", "Cloud SQL connection-error delta"),
        ("load_balancer.backend_5xx_delta", "load-balancer backend 5xx delta"),
        ("load_balancer.timeout_delta", "load-balancer timeout delta"),
        ("load_balancer.unhealthy_backend_count", "load-balancer unhealthy backend count"),
        ("load_balancer.dropped_connection_delta", "load-balancer dropped-connection delta"),
    ],
)
def test_strict_gate_rejects_each_nonzero_health_delta(name, expected_label):
    metrics = _metrics()
    metrics.metrics[name] = _metric(name, 1)

    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), _summary(), metrics)

    assert f"{expected_label} must be zero" in verdict.failures


@pytest.mark.parametrize(
    ("name", "value", "expected_failure"),
    [
        ("guacd.ready_replicas", 1, "guacd ready replicas fell below the profile minimum"),
        ("guacd.cpu_utilization_pct", 81, "guacd CPU exceeded the saturation ceiling"),
        (
            "redis.connection_utilization_pct",
            76,
            "Redis connection utilization exceeded the saturation ceiling",
        ),
        ("redis.memory_utilization_pct", 76, "Redis memory utilization exceeded the saturation ceiling"),
        (
            "cloud_sql.connection_utilization_pct",
            76,
            "Cloud SQL connection utilization exceeded the saturation ceiling",
        ),
        ("cloud_sql.cpu_utilization_pct", 76, "Cloud SQL CPU exceeded the saturation ceiling"),
        (
            "load_balancer.backend_latency_p95_ms",
            2001,
            "load-balancer backend p95 exceeded the authored budget",
        ),
    ],
)
def test_strict_gate_rejects_each_saturation_threshold(name, value, expected_failure):
    metrics = _metrics()
    metrics.metrics[name] = _metric(name, value)

    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), _summary(), metrics)

    assert expected_failure in verdict.failures


@pytest.mark.parametrize("name", sorted(_metrics().metrics))
def test_strict_gate_fails_closed_when_any_required_metric_is_missing(name):
    metrics = _metrics()
    metrics.metrics.pop(name)

    verdict = evaluate_capacity_gate(CapacityGateBudget.p30(), _summary(), metrics)

    assert f"missing required metric {name}" in verdict.failures
