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

from event_load_harness.metrics.base import MetricsResult, MetricValue


def _datapoint_values(points: list, stat: str, is_pct: bool) -> list[float]:
    """Extract the requested statistic from each CloudWatch datapoint."""
    values: list[float] = []
    for point in points:
        value = point.get("ExtendedStatistics", {}).get(stat) if is_pct else point.get(stat)
        if value is not None:
            values.append(value)
    return values


def _aggregate(stat: str, values: list[float]) -> float | None:
    """Aggregate per-period datapoints by statistic. None for an empty window.

    Sum stats sum across the window (counts), percentile stats take the worst
    (max) tail observed, and averages take the mean.
    """
    if not values:
        return None
    if stat == "Sum":
        return sum(values)
    if stat in ("p95", "p99"):
        return max(values)
    return sum(values) / len(values)


# (cloudwatch_namespace, metric_name, statistic, unit, dimension_key, target_field, is_proxy, gap_label)
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
    ),
    ("AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "Sum", "count", "LoadBalancer", "alb", False, "ALB 5xx count"),
    (
        "AWS/ApplicationELB",
        "RejectedConnectionCount",
        "Sum",
        "count",
        "LoadBalancer",
        "alb",
        False,
        "ALB rejected connections",
    ),
    ("AWS/EC2", "CPUUtilization", "Average", "percent", "AutoScalingGroupName", "asg", False, "Portal EC2 average CPU"),
    ("AWS/RDS", "CPUUtilization", "Average", "percent", "DBInstanceIdentifier", "rds_instance", False, "RDS CPU"),
    (
        "AWS/RDS",
        "DatabaseConnections",
        "Average",
        "conn",
        "DBInstanceIdentifier",
        "rds_instance",
        True,
        "RDS connection-rate proxy",
    ),
    ("AWS/ElastiCache", "CPUUtilization", "Average", "percent", "CacheClusterId", "redis_cluster", False, "Redis CPU"),
    (
        "AWS/ElastiCache",
        "CurrConnections",
        "Average",
        "conn",
        "CacheClusterId",
        "redis_cluster",
        False,
        "Redis connections",
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
        for namespace, metric_name, stat, unit, dim_key, target_field, is_proxy, gap_label in _SPECS:
            dim_value = self.targets.get(target_field)
            if not dim_value:
                gaps.append(f"{gap_label} (no {target_field} configured)")
                continue
            value = self._query(namespace, metric_name, stat, dim_key, dim_value, window_start, window_end)
            if value is None:
                gaps.append(f"{gap_label} (no datapoints in window)")
                continue
            key = f"{target_field}.{metric_name}".lower()
            metrics[key] = MetricValue(
                name=key,
                value=value,
                unit=unit,
                provenance=f"{namespace} {metric_name} ({stat})" + (" [proxy]" if is_proxy else ""),
                is_proxy=is_proxy,
            )
        return MetricsResult(self.provider, window_start, window_end, metrics=metrics, gaps=gaps)

    def _query(self, namespace, metric_name, stat, dim_key, dim_value, start, end):
        """Aggregate one signal across the full run window, or None on any gap/failure.

        Percentile stats (p95/p99) must be requested via ``ExtendedStatistics``
        alone; sending both ``Statistics`` and ``ExtendedStatistics`` for a
        percentile makes CloudWatch reject the call. A run longer than one Period
        returns multiple datapoints, so every datapoint is aggregated (sum / mean /
        max) rather than collapsing the window to its latest point.
        """
        client = self._get_client()
        is_pct = stat in ("p95", "p99")
        kwargs = {
            "Namespace": namespace,
            "MetricName": metric_name,
            "Dimensions": [{"Name": dim_key, "Value": dim_value}],
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
        values = _datapoint_values(resp.get("Datapoints", []), stat, is_pct)
        return _aggregate(stat, values)
