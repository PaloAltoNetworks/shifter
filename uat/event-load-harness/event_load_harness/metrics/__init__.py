"""Metrics adapters and the factory that selects one from run config."""

from __future__ import annotations

from event_load_harness.metrics.aws import AwsMetricsAdapter
from event_load_harness.metrics.base import MetricsAdapter, MetricsResult, MetricValue
from event_load_harness.metrics.client_only import ClientOnlyAdapter

__all__ = [
    "AwsMetricsAdapter",
    "ClientOnlyAdapter",
    "MetricValue",
    "MetricsAdapter",
    "MetricsResult",
    "build_adapter",
]


def build_adapter(metric_source: str, region: str | None, targets: dict[str, str]) -> MetricsAdapter:
    """Construct the metrics adapter named by ``metric_source``.

    ``client-only`` (the default) takes no region or targets. ``aws`` is the
    thin optional plug. Unknown sources raise so a typo fails before the run.
    """
    if metric_source == "client-only":
        return ClientOnlyAdapter()
    if metric_source == "aws":
        return AwsMetricsAdapter(region=region or "us-east-2", targets=targets)
    raise ValueError(f"unknown metric_source {metric_source!r}")
