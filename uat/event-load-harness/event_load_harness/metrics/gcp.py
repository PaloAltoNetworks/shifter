"""Read-only GCP Cloud Monitoring adapter for the strict event gate (#1816)."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from event_load_harness.metrics.base import MetricsResult, MetricValue


@dataclass(frozen=True)
class GcpSignal:
    name: str
    metric_type: str
    unit: str
    reducer: str
    component: str | None = None
    metric_filter: str | None = None
    evidence_source: str = "monitoring"


class GcpMetricReader(Protocol):
    def read(self, signal: GcpSignal, window_start: str, window_end: str, targets: dict[str, str]) -> float | None: ...


_SIGNALS = (
    GcpSignal("portal.pod_restart_delta", "kubernetes.io/container/restart_count", "count", "delta", "portal"),
    GcpSignal(
        "guacamole_client.pod_restart_delta",
        "kubernetes.io/container/restart_count",
        "count",
        "delta",
        "guacamole-client",
    ),
    GcpSignal("guacd.pod_restart_delta", "kubernetes.io/container/restart_count", "count", "delta", "guacd"),
    GcpSignal(
        "guacd.ready_replicas",
        "kubernetes/deployment/status/readyReplicas",
        "count",
        "latest",
        "guacd",
        evidence_source="kubectl",
    ),
    GcpSignal("guacd.cpu_utilization_pct", "kubernetes.io/container/cpu/limit_utilization", "percent", "max", "guacd"),
    GcpSignal("redis.connections_peak", "redis.googleapis.com/clients/connected", "connections", "max"),
    GcpSignal(
        "redis.memory_utilization_pct",
        "redis.googleapis.com/stats/memory/usage_ratio",
        "percent",
        "max",
    ),
    GcpSignal("redis.eviction_delta", "redis.googleapis.com/stats/evicted_keys", "count", "sum"),
    GcpSignal(
        "redis.rejected_connection_delta",
        "redis.googleapis.com/stats/reject_connections_count",
        "count",
        "sum",
    ),
    GcpSignal(
        "cloud_sql.connections_peak",
        "cloudsql.googleapis.com/database/postgresql/num_backends",
        "connections",
        "max",
    ),
    GcpSignal(
        "cloud_sql.connection_error_delta",
        "cloudsql.googleapis.com/database/network/connection_attempt_count",
        "count",
        "sum",
        metric_filter='metric.labels.login_status = "failed"',
    ),
    GcpSignal("cloud_sql.cpu_utilization_pct", "cloudsql.googleapis.com/database/cpu/utilization", "percent", "max"),
    GcpSignal(
        "load_balancer.backend_latency_p95_ms",
        "loadbalancing.googleapis.com/https/backend_latencies",
        "ms",
        "p95",
    ),
    GcpSignal(
        "load_balancer.backend_5xx_delta",
        "loadbalancing.googleapis.com/https/backend_request_count",
        "count",
        "sum",
        metric_filter="metric.labels.response_code_class = 500",
    ),
    GcpSignal(
        "load_balancer.timeout_delta",
        "loadbalancing.googleapis.com/https/request_count",
        "count",
        "sum",
        metric_filter="metric.labels.response_code = 504",
    ),
    GcpSignal(
        "load_balancer.unhealthy_backend_count",
        "compute/backendServices/getHealth",
        "count",
        "latest",
        evidence_source="gcloud",
    ),
    GcpSignal(
        "load_balancer.dropped_connection_delta",
        "loadbalancing.googleapis.com/https/request_count",
        "count",
        "sum",
        metric_filter="metric.labels.response_code_class = 0",
    ),
)


class GcpMetricsAdapter:
    provider = "gcp"

    def __init__(
        self,
        region: str,
        targets: dict[str, str],
        *,
        reader: GcpMetricReader | None = None,
    ) -> None:
        self.region = region
        self.targets = dict(targets or {})
        self._reader = reader or GcpEvidenceReader()

    def collect(self, window_start: str, window_end: str) -> MetricsResult:
        metrics: dict[str, MetricValue] = {}
        gaps: list[str] = []
        for signal in _SIGNALS:
            try:
                value = self._reader.read(signal, window_start, window_end, self.targets)
            except Exception:
                value = None
            if value is None:
                gaps.append(f"{signal.name} (no parseable datapoints in window)")
                continue
            if signal.unit == "percent" and 0 <= value <= 1:
                value *= 100
            metrics[signal.name] = MetricValue(
                name=signal.name,
                value=float(value),
                unit=signal.unit,
                provenance=_provenance(signal),
            )
        self._derive_ratio(metrics, gaps, "redis", "redis_connection_budget")
        self._derive_ratio(metrics, gaps, "cloud_sql", "sql_connection_budget")
        return MetricsResult(self.provider, window_start, window_end, metrics=metrics, gaps=gaps)

    def _derive_ratio(
        self,
        metrics: dict[str, MetricValue],
        gaps: list[str],
        prefix: str,
        budget_key: str,
    ) -> None:
        source_name = f"{prefix}.connections_peak"
        output_name = f"{prefix}.connection_utilization_pct"
        source = metrics.get(source_name)
        try:
            budget = float(self.targets.get(budget_key, ""))
        except ValueError:
            budget = 0
        if source is None or budget <= 0:
            gaps.append(f"{output_name} (missing peak or authored connection budget)")
            return
        metrics[output_name] = MetricValue(
            name=output_name,
            value=source.value / budget * 100.0,
            unit="percent",
            provenance=f"{source.name} / authored {budget_key}",
        )


class CloudMonitoringReader:
    """Thin lazy client; it performs only time-series list/read operations."""

    def __init__(self, client=None) -> None:
        self._client = client

    def _get_client(self):
        if self._client is None:
            try:
                from google.cloud import monitoring_v3
            except ImportError as exc:  # pragma: no cover - optional live dependency
                raise RuntimeError("install event-load-harness[gcp] for Cloud Monitoring evidence") from exc
            self._client = monitoring_v3.MetricServiceClient()
        return self._client

    def read(self, signal: GcpSignal, window_start: str, window_end: str, targets: dict[str, str]) -> float | None:
        project_id = targets.get("project_id", "")
        if not project_id:
            return None
        from google.cloud import monitoring_v3

        interval = monitoring_v3.TimeInterval(
            {
                "start_time": _timestamp(window_start),
                "end_time": _timestamp(window_end),
            }
        )
        filters = [f'metric.type = "{signal.metric_type}"']
        if signal.metric_filter:
            filters.append(signal.metric_filter)
        metric_namespace = _metric_namespace(signal.metric_type)
        cluster = targets.get("cluster")
        namespace = targets.get("namespace")
        if metric_namespace == "kubernetes.io":
            if cluster:
                filters.append(f'resource.labels.cluster_name = "{cluster}"')
            if namespace:
                filters.append(f'resource.labels.namespace_name = "{namespace}"')
            if signal.component:
                filters.append(f'resource.labels.container_name = "{signal.component}"')
        sql_instance = targets.get("sql_instance")
        if metric_namespace == "cloudsql.googleapis.com" and sql_instance:
            filters.append(f'resource.labels.database_id = "{project_id}:{sql_instance}"')
        redis_instance = targets.get("redis_instance")
        if metric_namespace == "redis.googleapis.com" and redis_instance:
            filters.append(f'resource.labels.instance_id = "{redis_instance}"')
        backend_name = targets.get("backend_name")
        if metric_namespace == "loadbalancing.googleapis.com" and backend_name:
            filters.append(f'resource.labels.backend_target_name = "{backend_name}"')
        request = {
            "name": f"projects/{project_id}",
            "filter": " AND ".join(filters),
            "interval": interval,
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            "aggregation": _aggregation(monitoring_v3, signal.reducer),
        }
        values: list[float] = []
        for series in self._get_client().list_time_series(request=request):
            for point in series.points:
                raw = point.value.double_value or point.value.int64_value
                values.append(float(raw))
        return _reduce(values, signal.reducer)


class GcpEvidenceReader:
    """Combine Cloud Monitoring with bounded read-only workload and LB health reads."""

    def __init__(self, monitoring_reader: CloudMonitoringReader | None = None) -> None:
        self._monitoring = monitoring_reader or CloudMonitoringReader()

    def read(self, signal: GcpSignal, window_start: str, window_end: str, targets: dict[str, str]) -> float | None:
        if signal.evidence_source == "kubectl":
            return _ready_replicas(targets, signal.component or "")
        if signal.evidence_source == "gcloud":
            return _unhealthy_backends(targets)
        return self._monitoring.read(signal, window_start, window_end, targets)


def _ready_replicas(targets: dict[str, str], deployment: str) -> float | None:
    namespace = targets.get("namespace")
    if not namespace or not deployment:
        return None
    return _json_command_number(
        ["kubectl", "get", "deployment", deployment, "--namespace", namespace, "--output", "json"],
        lambda payload: payload.get("status", {}).get("readyReplicas", 0) if isinstance(payload, dict) else None,
    )


def _unhealthy_backends(targets: dict[str, str]) -> float | None:
    project = targets.get("project_id")
    backend = targets.get("backend_name")
    if not project or not backend:
        return None

    def count_unhealthy(payload: object) -> int:
        groups = payload if isinstance(payload, list) else []
        statuses = [
            status
            for group in groups
            if isinstance(group, dict)
            for status in group.get("status", {}).get("healthStatus", [])
            if isinstance(status, dict)
        ]
        return sum(status.get("healthState") != "HEALTHY" for status in statuses)

    return _json_command_number(
        [
            "gcloud",
            "compute",
            "backend-services",
            "get-health",
            backend,
            "--global",
            "--project",
            project,
            "--format=json",
        ],
        count_unhealthy,
    )


def _json_command_number(argv: list[str], extract: Callable[[object], object]) -> float | None:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
        if completed.returncode != 0:
            return None
        return float(extract(json.loads(completed.stdout)))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _aggregation(monitoring_v3, reducer: str):
    aligners = {
        "delta": monitoring_v3.Aggregation.Aligner.ALIGN_DELTA,
        "sum": monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
        "max": monitoring_v3.Aggregation.Aligner.ALIGN_MAX,
        "p95": monitoring_v3.Aggregation.Aligner.ALIGN_PERCENTILE_95,
    }
    reducers = {
        "delta": monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
        "sum": monitoring_v3.Aggregation.Reducer.REDUCE_SUM,
        "max": monitoring_v3.Aggregation.Reducer.REDUCE_MAX,
        "p95": monitoring_v3.Aggregation.Reducer.REDUCE_MAX,
    }
    return monitoring_v3.Aggregation(
        {
            "alignment_period": {"seconds": 60},
            "per_series_aligner": aligners.get(reducer, monitoring_v3.Aggregation.Aligner.ALIGN_MAX),
            "cross_series_reducer": reducers.get(reducer, monitoring_v3.Aggregation.Reducer.REDUCE_MAX),
        }
    )


def _reduce(values: list[float], reducer: str) -> float | None:
    if not values:
        return None
    if reducer in {"max", "p95", "latest"}:
        return max(values)
    if reducer == "delta":
        return sum(values)
    return sum(values)


def _timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _metric_namespace(metric_type: str) -> str:
    """Return the exact namespace segment of one Cloud Monitoring metric type."""
    namespace, separator, _ = metric_type.partition("/")
    return namespace if separator else ""


def _provenance(signal: GcpSignal) -> str:
    if signal.evidence_source == "kubectl":
        return "read-only Kubernetes Deployment status"
    if signal.evidence_source == "gcloud":
        return "read-only GCP backend-service health"
    return f"Google Cloud Monitoring {signal.metric_type} ({signal.reducer})"
