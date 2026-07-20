"""GCP Cloud Monitoring adapter for the portal capacity emitter (PLAT-002, #671).

AWS publishes the per-worker ``Shifter/PortalCapacity`` gauges to CloudWatch via
boto3 (``config/capacity_metrics.py``). GCP has no CloudWatch, so this module
gives a ``put_metric_data``-compatible adapter that translates the same
provider-neutral MetricData into Cloud Monitoring TimeSeries and writes them with
``create_time_series`` — the emitter (``PortalCapacityEmitter``) stays
provider-agnostic and the AWS path keeps no dependency on google libraries.

The CloudWatch namespace ``Shifter/PortalCapacity`` maps onto the custom metric
type prefix ``custom.googleapis.com/shifter/portal_capacity/<MetricName>``; the
single ``NamePrefix`` dimension becomes a low-cardinality metric label. Custom
metrics are written against the project-scoped ``global`` monitored resource;
``metric_kind`` / ``value_type`` are descriptor properties and must NOT be set on
a written series (the API auto-creates the descriptor as GAUGE/DOUBLE).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from google.cloud.monitoring_v3 import MetricServiceClient

logger = logging.getLogger(__name__)

_METRIC_TYPE_PREFIX = "custom.googleapis.com/shifter/portal_capacity/"
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _label_key(dimension_name: str) -> str:
    """Convert a CloudWatch dimension name to a Cloud Monitoring label key.

    Label keys must match ``[a-z][a-z0-9_]*``; ``NamePrefix`` -> ``name_prefix``.
    """
    return _CAMEL_BOUNDARY.sub("_", dimension_name).lower()


def build_time_series(
    metric_data: list[dict[str, Any]],
    *,
    project_id: str,
    timestamp_seconds: int,
) -> list[dict[str, Any]]:
    """Translate CloudWatch-shaped MetricData into Cloud Monitoring TimeSeries mappings.

    Pure function: returns plain dicts (one per metric) suitable for
    ``monitoring_v3.TimeSeries(mapping)``. Each entry's single numeric ``Value``
    becomes one gauge point at ``timestamp_seconds``; the ``NamePrefix`` dimension
    becomes a metric label. ``metric_kind`` / ``value_type`` are intentionally
    omitted (see module docstring).
    """
    resource = {"type": "global", "labels": {"project_id": project_id}}
    series: list[dict[str, Any]] = []
    for entry in metric_data:
        labels = {_label_key(dim["Name"]): str(dim["Value"]) for dim in entry.get("Dimensions", [])}
        series.append(
            {
                "metric": {
                    "type": _METRIC_TYPE_PREFIX + str(entry["MetricName"]),
                    "labels": labels,
                },
                "resource": resource,
                "points": [
                    {
                        "interval": {"end_time": {"seconds": int(timestamp_seconds)}},
                        "value": {"double_value": float(entry["Value"])},
                    }
                ],
            }
        )
    return series


class GCPMonitoringClient:
    """``put_metric_data``-compatible adapter that writes to Cloud Monitoring.

    Implements the same dynamic surface ``PortalCapacityEmitter`` calls on the
    boto3 CloudWatch client (``put_metric_data(Namespace=..., MetricData=...)``),
    so the emitter does not branch on provider. ``now`` is injectable so the
    timestamp is testable without patching the clock.
    """

    def __init__(self, *, client: MetricServiceClient, project_id: str, now: Callable[[], float] = time.time) -> None:
        self._client = client
        self._project_id = project_id
        self._project_name = f"projects/{project_id}"
        self._now = now

    def put_metric_data(self, **kwargs: object) -> None:
        """Write one gauge point per metric to Cloud Monitoring.

        Mirrors the boto3 ``put_metric_data`` surface: ``MetricData`` carries the
        gauge entries the emitter builds. The CloudWatch ``Namespace`` keyword is
        accepted for signature parity but unused — the namespace is encoded in
        the metric type prefix.
        """
        from google.cloud import monitoring_v3

        metric_data = cast("list[dict[str, Any]]", kwargs["MetricData"])
        mappings = build_time_series(metric_data, project_id=self._project_id, timestamp_seconds=int(self._now()))
        time_series = [monitoring_v3.TimeSeries(mapping) for mapping in mappings]
        self._client.create_time_series(name=self._project_name, time_series=time_series)


def build_gcp_client_factory() -> Callable[[], GCPMonitoringClient]:
    """Return a factory that builds a Cloud Monitoring-backed capacity client.

    The factory is invoked once per worker by ``build_emitter_from_config``; a
    construction failure (missing project, google libs, ADC) is caught there and
    degrades to no emitter rather than failing worker boot.
    """

    def _factory() -> GCPMonitoringClient:
        """Construct a Cloud Monitoring-backed capacity client for this worker."""
        from google.cloud import monitoring_v3

        from shared.cloud.gcp.base import get_project_id

        project_id = get_project_id()
        if not project_id:
            raise ValueError("GCP project ID is required to publish portal capacity metrics")
        return GCPMonitoringClient(client=monitoring_v3.MetricServiceClient(), project_id=project_id)

    return _factory
