"""Metrics-adapter contract and the normalized result it returns.

The adapter is the swappable seam: ``client-only`` (default) measures nothing
provider-side and names its gaps honestly; ``aws`` is a thin CloudWatch plug; a
future GCP/Prometheus/OpenShift adapter implements the same protocol without
touching load generation or reporting. Keeping the coupling here means a
platform migration replaces one adapter, not the harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class MetricValue:
    """One collected signal, with provenance and an honest proxy flag."""

    name: str
    value: float
    unit: str
    provenance: str
    is_proxy: bool = False


@dataclass(frozen=True)
class MetricsResult:
    """Provider-side metrics for a single run window, plus named gaps."""

    provider: str
    window_start: str
    window_end: str
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)


@runtime_checkable
class MetricsAdapter(Protocol):
    """Collect provider metrics over the run's [start, end] window."""

    provider: str

    def collect(self, window_start: str, window_end: str) -> MetricsResult: ...
