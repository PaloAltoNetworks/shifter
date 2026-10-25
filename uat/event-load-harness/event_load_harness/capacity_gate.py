"""Fail-closed verdict for the public-path Guacamole event gate (#1816)."""

from __future__ import annotations

from dataclasses import dataclass

from installation.capacity_profiles_gcp import resolve_capacity_profile

from event_load_harness.metrics.base import MetricsResult


@dataclass(frozen=True)
class CapacityGateBudget:
    capacity_profile_id: str
    concurrency: int
    hold_seconds: float
    bootstrap_p95_ms: float
    bootstrap_p99_ms: float
    required_guacd_replicas: int
    guacd_max_cpu_pct: float
    redis_max_utilization_pct: float
    cloud_sql_max_utilization_pct: float
    load_balancer_p95_ms: float

    @classmethod
    def p30(cls) -> CapacityGateBudget:
        return cls.from_profile_id("gcp-shared-v1-p30")

    @classmethod
    def from_profile_id(cls, profile_id: str) -> CapacityGateBudget:
        profile = resolve_capacity_profile(profile_id)
        gate = profile.gate
        return cls(
            capacity_profile_id=profile.profile_id,
            concurrency=gate.concurrency,
            hold_seconds=gate.hold_seconds,
            bootstrap_p95_ms=gate.bootstrap_p95_ms,
            bootstrap_p99_ms=gate.bootstrap_p99_ms,
            required_guacd_replicas=gate.required_guacd_replicas,
            guacd_max_cpu_pct=gate.guacd_max_cpu_pct,
            redis_max_utilization_pct=profile.redis.max_utilization_pct,
            cloud_sql_max_utilization_pct=profile.cloud_sql.max_utilization_pct,
            load_balancer_p95_ms=gate.load_balancer_p95_ms,
        )


@dataclass(frozen=True)
class CapacityGateVerdict:
    passed: bool
    failures: tuple[str, ...]


def render_capacity_gate_section(profile_id: str, verdict: CapacityGateVerdict) -> str:
    lines = ["## Strict shared-service capacity gate", "", f"- Capacity profile: `{profile_id}`"]
    lines.append(f"- Verdict: **{'PASS' if verdict.passed else 'FAIL'}**")
    if verdict.failures:
        lines.append("- Failed checks:")
        lines.extend(f"  - {failure}" for failure in verdict.failures)
    else:
        lines.append("- All authored client, tunnel, provider, and saturation thresholds passed.")
    return "\n".join(lines) + "\n"


_REQUIRED_ZERO_METRICS: dict[str, str] = {
    "portal.pod_restart_delta": "portal pod restart delta",
    "guacamole_client.pod_restart_delta": "guacamole-client pod restart delta",
    "guacd.pod_restart_delta": "guacd pod restart delta",
    "redis.eviction_delta": "Redis eviction delta",
    "redis.rejected_connection_delta": "Redis rejected-connection delta",
    "cloud_sql.connection_error_delta": "Cloud SQL connection-error delta",
    "load_balancer.backend_5xx_delta": "load-balancer backend 5xx delta",
    "load_balancer.timeout_delta": "load-balancer timeout delta",
    "load_balancer.unhealthy_backend_count": "load-balancer unhealthy backend count",
    "load_balancer.dropped_connection_delta": "load-balancer dropped-connection delta",
}

_REQUIRED_METRICS = frozenset(
    {
        *_REQUIRED_ZERO_METRICS,
        "guacd.ready_replicas",
        "guacd.cpu_utilization_pct",
        "redis.connection_utilization_pct",
        "redis.memory_utilization_pct",
        "cloud_sql.connection_utilization_pct",
        "cloud_sql.cpu_utilization_pct",
        "load_balancer.backend_latency_p95_ms",
    }
)


def evaluate_capacity_gate(
    budget: CapacityGateBudget,
    stats_summary: dict[str, object],
    metrics: MetricsResult,
) -> CapacityGateVerdict:
    """Evaluate all client and provider evidence; missing data is a failure."""
    failures: list[str] = []
    route = _route(stats_summary)
    if route is None:
        failures.append("missing guacamole:session-hold route evidence")
    else:
        _evaluate_route(budget, route, failures)

    missing = sorted(_REQUIRED_METRICS - metrics.metrics.keys())
    failures.extend(f"missing required metric {name}" for name in missing)
    _evaluate_metrics(budget, metrics, failures)
    return CapacityGateVerdict(passed=not failures, failures=tuple(failures))


def _route(stats_summary: dict[str, object]) -> dict[str, object] | None:
    routes = stats_summary.get("routes")
    if not isinstance(routes, dict):
        return None
    route = routes.get("guacamole:session-hold")
    return route if isinstance(route, dict) else None


def _evaluate_route(budget: CapacityGateBudget, route: dict[str, object], failures: list[str]) -> None:
    if route.get("requests") != budget.concurrency:
        failures.append(f"expected {budget.concurrency} concurrent tunnel attempts")
    if route.get("ok") != budget.concurrency or route.get("errors") != 0:
        failures.append("every participant tunnel must succeed")
    if route.get("display_synchronized") != budget.concurrency:
        failures.append("every participant tunnel must reach display synchronization")
    if _number(route.get("ws_dropped")) != 0:
        failures.append("unexpected tunnel drop during sustained hold")
    if _number(route.get("held_seconds_min")) < budget.hold_seconds:
        failures.append(f"every tunnel must remain held for at least {budget.hold_seconds:g}s")

    latency = route.get("latency_ms")
    if not isinstance(latency, dict):
        failures.append("missing bootstrap latency percentiles")
        return
    if _number(latency.get("p95")) > budget.bootstrap_p95_ms:
        failures.append("bootstrap p95 exceeded the authored budget")
    if _number(latency.get("p99")) > budget.bootstrap_p99_ms:
        failures.append("bootstrap p99 exceeded the authored budget")


def _evaluate_metrics(budget: CapacityGateBudget, metrics: MetricsResult, failures: list[str]) -> None:
    for name, label in _REQUIRED_ZERO_METRICS.items():
        if name in metrics.metrics and metrics.metrics[name].value != 0:
            failures.append(f"{label} must be zero")
    if _metric(metrics, "guacd.ready_replicas") < budget.required_guacd_replicas:
        failures.append("guacd ready replicas fell below the profile minimum")
    if _metric(metrics, "guacd.cpu_utilization_pct") > budget.guacd_max_cpu_pct:
        failures.append("guacd CPU exceeded the saturation ceiling")
    if _metric(metrics, "redis.connection_utilization_pct") > budget.redis_max_utilization_pct:
        failures.append("Redis connection utilization exceeded the saturation ceiling")
    if _metric(metrics, "redis.memory_utilization_pct") > budget.redis_max_utilization_pct:
        failures.append("Redis memory utilization exceeded the saturation ceiling")
    if _metric(metrics, "cloud_sql.connection_utilization_pct") > budget.cloud_sql_max_utilization_pct:
        failures.append("Cloud SQL connection utilization exceeded the saturation ceiling")
    if _metric(metrics, "cloud_sql.cpu_utilization_pct") > budget.cloud_sql_max_utilization_pct:
        failures.append("Cloud SQL CPU exceeded the saturation ceiling")
    if _metric(metrics, "load_balancer.backend_latency_p95_ms") > budget.load_balancer_p95_ms:
        failures.append("load-balancer backend p95 exceeded the authored budget")


def _metric(metrics: MetricsResult, name: str) -> float:
    value = metrics.metrics.get(name)
    return value.value if value is not None else float("nan")


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else float("inf")
