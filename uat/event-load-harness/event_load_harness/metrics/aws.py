"""Thin AWS CloudWatch metrics plug (optional).

This adapter is intentionally a small, replaceable plug behind the
``MetricsAdapter`` protocol. ``boto3`` is an optional dependency (``[aws]``
extra); ``client-only`` mode needs none of it. The adapter never fabricates a
signal: anything not configured, or any query that fails, becomes a named gap
rather than a guessed number. Proxy-derived signals are flagged ``is_proxy``.

It reads provider telemetry only; it issues no mutating AWS calls and stores no
credentials or DSNs. Resource identifiers are passed in by the operator.
"""

from __future__ import annotations

from itertools import pairwise

from event_load_harness.metrics.base import MetricsResult, MetricValue


def _datapoint_series(points: list, stat: str, is_pct: bool) -> list[tuple[object, float]]:
    """Extract timestamped values from CloudWatch datapoints, sorted by time."""
    series: list[tuple[object, float]] = []
    for point in points:
        value = point.get("ExtendedStatistics", {}).get(stat) if is_pct else point.get(stat)
        timestamp = point.get("Timestamp")
        if value is not None and timestamp is not None:
            series.append((timestamp, float(value)))
    return sorted(series, key=lambda item: item[0])


def _datapoint_values(points: list, stat: str, is_pct: bool) -> list[float]:
    """Extract the requested statistic from each CloudWatch datapoint."""
    return [value for _, value in _datapoint_series(points, stat, is_pct)]


def _aggregate(stat: str, values: list[float]) -> float | None:
    """Aggregate per-period datapoints by statistic. None for an empty window.

    Sum stats sum across the window (counts), percentile stats take the worst
    (max) tail observed, and averages take the mean.
    """
    if not values:
        return None
    if stat == "Sum":
        return sum(values)
    if stat in ("p95", "p99", "Maximum"):
        return max(values)
    if stat == "Minimum":
        return min(values)
    return sum(values) / len(values)


def _elapsed_seconds(start, end) -> float:
    delta = end - start
    if hasattr(delta, "total_seconds"):
        return float(delta.total_seconds())
    try:
        return float(delta)
    except (TypeError, ValueError):
        return 0.0


def _connection_churn_proxy(points: list) -> float | None:
    """Lower-bound connection churn proxy from active-connection sample deltas.

    CloudWatch ``DatabaseConnections`` is a sampled active-connection count, not
    an exact open/close counter. Summing absolute sample-to-sample deltas gives
    a conservative lower bound: short-lived open/close cycles between samples
    remain invisible and must be called out in the report.
    """
    series = _datapoint_series(points, "Average", is_pct=False)
    if len(series) < 2:
        return None
    total_delta = sum(abs(current[1] - previous[1]) for previous, current in pairwise(series))
    elapsed = _elapsed_seconds(series[0][0], series[-1][0])
    if elapsed <= 0:
        elapsed = 300.0 * (len(series) - 1)
    return total_delta / elapsed if elapsed > 0 else None


# (
#   cloudwatch_namespace, metric_name, statistic, unit, dimension_key,
#   target_field, is_proxy, gap_label, output_name
# )
_SPECS = [
    (
        "AWS/ApplicationELB",
        "TargetResponseTime",
        "p95",
        "s",
        "LoadBalancer",
        "alb",
        False,
        "ALB TargetResponseTime p95",
        "targetresponsetime",
    ),
    (
        "AWS/ApplicationELB",
        "HTTPCode_Target_5XX_Count",
        "Sum",
        "count",
        "LoadBalancer",
        "alb",
        False,
        "ALB 5xx count",
        "httpcode_target_5xx_count",
    ),
    (
        "AWS/ApplicationELB",
        "RejectedConnectionCount",
        "Sum",
        "count",
        "LoadBalancer",
        "alb",
        False,
        "ALB rejected connections",
        "rejectedconnectioncount",
    ),
    (
        "AWS/ApplicationELB",
        "ActiveConnectionCount",
        "Maximum",
        "count",
        "LoadBalancer",
        "alb",
        False,
        "ALB active connections",
        "activeconnectioncount",
    ),
    (
        # App-side portal capacity gauges (#940), Shifter/PortalCapacity namespace,
        # dimensioned only by the environment NamePrefix. Busy ratio is reported as
        # the fleet mean (Average) and the hottest worker (Maximum); they answer
        # different questions during a saturation run.
        "Shifter/PortalCapacity",
        "WorkerBusyRatio",
        "Average",
        "ratio",
        "NamePrefix",
        "name_prefix",
        False,
        "Portal worker busy ratio (fleet mean)",
        "workerbusyratio",
    ),
    (
        "Shifter/PortalCapacity",
        "WorkerBusyRatio",
        "Maximum",
        "ratio",
        "NamePrefix",
        "name_prefix",
        False,
        "Portal worker busy ratio (hottest worker)",
        "workerbusyratio_peak",
    ),
    (
        # Count gauge: with the emitter publish interval aligned to the metric
        # period, Sum across the same-dimension samples approximates the fleet total.
        "Shifter/PortalCapacity",
        "WorkerInFlightRequests",
        "Sum",
        "count",
        "NamePrefix",
        "name_prefix",
        False,
        "Portal in-flight HTTP requests (fleet)",
        "workerinflightrequests",
    ),
    (
        "Shifter/PortalCapacity",
        "TerminalActiveSessions",
        "Sum",
        "count",
        "NamePrefix",
        "name_prefix",
        False,
        "Portal terminal active sessions (fleet)",
        "terminalactivesessions",
    ),
    (
        "AWS/EC2",
        "CPUUtilization",
        "Average",
        "percent",
        "AutoScalingGroupName",
        "asg",
        False,
        "Portal EC2 average CPU",
        "cpuutilization",
    ),
    (
        "AWS/RDS",
        "CPUUtilization",
        "Average",
        "percent",
        "DBInstanceIdentifier",
        "rds_instance",
        False,
        "RDS CPU",
        "cpuutilization",
    ),
    (
        "AWS/RDS",
        "DatabaseConnections",
        "Average",
        "conn",
        "DBInstanceIdentifier",
        "rds_instance",
        False,
        "RDS average connections",
        "databaseconnections",
    ),
    (
        "AWS/RDS",
        "DatabaseConnections",
        "Maximum",
        "conn",
        "DBInstanceIdentifier",
        "rds_instance",
        False,
        "RDS peak connections",
        "databaseconnections_peak",
    ),
    (
        "AWS/ElastiCache",
        "CPUUtilization",
        "Average",
        "percent",
        "CacheClusterId",
        "redis_cluster",
        False,
        "Redis CPU",
        "cpuutilization",
    ),
    (
        "AWS/ElastiCache",
        "CurrConnections",
        "Average",
        "conn",
        "CacheClusterId",
        "redis_cluster",
        False,
        "Redis connections",
        "currconnections",
    ),
]


class AwsMetricsAdapter:
    provider = "aws"

    def __init__(self, region: str, targets: dict[str, str], client=None) -> None:
        self.region = region
        self.targets = targets or {}
        self._client = client
        self._client_constructed = client is not None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3  # lazy: only needed when a target is actually configured
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    "the aws metric source needs boto3; install with `pip install event-load-harness[aws]`"
                ) from exc
            self._client = boto3.client("cloudwatch", region_name=self.region)
            self._client_constructed = True
        return self._client

    def collect(self, window_start: str, window_end: str) -> MetricsResult:
        metrics: dict[str, MetricValue] = {}
        gaps: list[str] = []
        for namespace, metric_name, stat, unit, dim_key, target_field, is_proxy, gap_label, output_name in _SPECS:
            dim_value = self.targets.get(target_field)
            if not dim_value:
                gaps.append(f"{gap_label} (no {target_field} configured)")
                continue
            value = self._query(namespace, metric_name, stat, dim_key, dim_value, window_start, window_end)
            if value is None:
                gaps.append(f"{gap_label} (no datapoints in window)")
                continue
            key = f"{target_field}.{output_name}".lower()
            metrics[key] = MetricValue(
                name=key,
                value=value,
                unit=unit,
                provenance=f"{namespace} {metric_name} ({stat})" + (" [proxy]" if is_proxy else ""),
                is_proxy=is_proxy,
            )
        self._collect_request_count_per_target(window_start, window_end, metrics, gaps)
        self._collect_rds_connection_churn(window_start, window_end, metrics, gaps)
        return MetricsResult(self.provider, window_start, window_end, metrics=metrics, gaps=gaps)

    def _collect_request_count_per_target(self, window_start, window_end, metrics, gaps) -> None:
        """Portal scale-out signal (#940): requests-per-target.

        AWS publishes ``RequestCountPerTarget`` under "Per AppELB, per TG" — the
        ``LoadBalancer`` + ``TargetGroup`` dimension PAIR — not ``TargetGroup``
        alone, so it needs both the ``alb`` (LoadBalancer suffix) and
        ``target_group`` targets; querying ``TargetGroup`` alone returns no
        datapoints. ``Sum`` is the only meaningful statistic for this metric.
        """
        alb = self.targets.get("alb")
        target_group = self.targets.get("target_group")
        if not alb or not target_group:
            gaps.append("ALB RequestCountPerTarget (needs both alb and target_group configured)")
            return
        value = self._query_dimensions(
            "AWS/ApplicationELB",
            "RequestCountPerTarget",
            "Sum",
            [{"Name": "LoadBalancer", "Value": alb}, {"Name": "TargetGroup", "Value": target_group}],
            window_start,
            window_end,
        )
        if value is None:
            gaps.append("ALB RequestCountPerTarget (no datapoints in window)")
            return
        key = "target_group.requestcountpertarget"
        metrics[key] = MetricValue(
            name=key,
            value=value,
            unit="count",
            provenance="AWS/ApplicationELB RequestCountPerTarget (Sum, LoadBalancer+TargetGroup)",
            is_proxy=False,
        )

    def _collect_rds_connection_churn(self, window_start, window_end, metrics, gaps) -> None:
        dim_value = self.targets.get("rds_instance")
        if not dim_value:
            return
        points = self._query_datapoints(
            "AWS/RDS",
            "DatabaseConnections",
            "Average",
            [{"Name": "DBInstanceIdentifier", "Value": dim_value}],
            window_start,
            window_end,
        )
        if not points:
            gaps.append("RDS connection churn proxy (no datapoints in window)")
            return
        value = _connection_churn_proxy(points)
        if value is None:
            gaps.append("RDS connection churn proxy (needs at least two DatabaseConnections samples)")
            return
        key = "rds_instance.connection_churn_proxy"
        metrics[key] = MetricValue(
            name=key,
            value=value,
            unit="conn/s",
            provenance="AWS/RDS DatabaseConnections (sample-to-sample absolute delta lower-bound proxy) [proxy]",
            is_proxy=True,
        )

    def _query(self, namespace, metric_name, stat, dim_key, dim_value, start, end):
        """Aggregate one single-dimension signal across the full run window.

        Percentile stats (p95/p99) must be requested via ``ExtendedStatistics``
        alone; sending both ``Statistics`` and ``ExtendedStatistics`` for a
        percentile makes CloudWatch reject the call. A run longer than one Period
        returns multiple datapoints, so every datapoint is aggregated (sum / mean /
        max) rather than collapsing the window to its latest point.
        """
        return self._query_dimensions(namespace, metric_name, stat, [{"Name": dim_key, "Value": dim_value}], start, end)

    def _query_dimensions(self, namespace, metric_name, stat, dimensions, start, end):
        """Aggregate a signal identified by a full dimension set (one or more dims)."""
        is_pct = stat in ("p95", "p99")
        points = self._query_datapoints(namespace, metric_name, stat, dimensions, start, end)
        if points is None:
            return None
        values = _datapoint_values(points, stat, is_pct)
        return _aggregate(stat, values)

    def _query_datapoints(self, namespace, metric_name, stat, dimensions, start, end):
        client = self._get_client()
        is_pct = stat in ("p95", "p99")
        kwargs = {
            "Namespace": namespace,
            "MetricName": metric_name,
            "Dimensions": dimensions,
            "StartTime": start,
            "EndTime": end,
            "Period": 300,
        }
        if is_pct:
            kwargs["ExtendedStatistics"] = [stat]
        else:
            kwargs["Statistics"] = [stat]
        try:
            resp = client.get_metric_statistics(**kwargs)
        except Exception:
            return None
        return resp.get("Datapoints", [])
