"""Warm-pool observability metrics (#28).

Publishes warm-pool gauges and claim-outcome counters to their own
``Shifter/WarmPool`` namespace -- deliberately distinct from portal-capacity and
capacity-planning so the three series stay readable -- through a provider-aware
``put_metric_data``-compatible client selected by ``CLOUD_PROVIDER`` (CloudWatch on
AWS, Cloud Monitoring on GCP). It lives in ``shared`` rather than ``config`` because
the reconciler and launch claim path (``cms``) invoke it and may not import the
composition root; it mirrors the portal-capacity emitter's client surface so the
two stay conceptually one seam.

Emission is fail-soft: an observability blip never breaks the reconciler or a
launch. Dimensions are strictly low-cardinality -- pool bucket, backend/region
class, and a closed outcome -- never user, request, scenario, resource, account, or
project identifiers (preflight #28).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from django.conf import settings

from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)

_READY = "WarmPoolReady"
_PROVISIONING = "WarmPoolProvisioning"
_UNHEALTHY = "WarmPoolUnhealthy"
_CLAIMED = "WarmPoolClaimed"
_CLAIM_OUTCOME = "WarmPoolClaimOutcome"

CLAIM_HIT = "hit"
CLAIM_FALLBACK = "fallback"
_VALID_OUTCOMES = frozenset({CLAIM_HIT, CLAIM_FALLBACK})


class MetricPublisher(Protocol):
    """The ``put_metric_data(Namespace=..., MetricData=...)`` surface both providers expose."""

    def put_metric_data(self, **kwargs: object) -> object: ...


@dataclass(frozen=True)
class WarmPoolBucketSnapshot:
    """Per-bucket pool depth for one metrics sample. Counts only; no identities."""

    bucket_id: str
    backend: str
    region: str
    ready: int
    provisioning: int
    unhealthy: int
    claimed: int


def _namespace() -> str:
    """Return the configured warm-pool metrics namespace (default ``Shifter/WarmPool``)."""
    return getattr(settings, "WARM_POOL_METRICS_NAMESPACE", "Shifter/WarmPool")


def _dimensions(bucket_id: str, backend: str, region: str) -> list[dict[str, str]]:
    """Return the low-cardinality metric dimensions for one pool bucket."""
    dims = [{"Name": "Bucket", "Value": bucket_id}, {"Name": "Backend", "Value": backend}]
    if region:
        dims.append({"Name": "Region", "Value": region})
    return dims


def build_gauge_metric_data(snapshots: list[WarmPoolBucketSnapshot]) -> list[dict[str, Any]]:
    """Translate per-bucket snapshots into ``put_metric_data`` gauge entries."""
    data: list[dict[str, Any]] = []
    for snap in snapshots:
        dims = _dimensions(snap.bucket_id, snap.backend, snap.region)
        for name, value in (
            (_READY, snap.ready),
            (_PROVISIONING, snap.provisioning),
            (_UNHEALTHY, snap.unhealthy),
            (_CLAIMED, snap.claimed),
        ):
            data.append({"MetricName": name, "Dimensions": dims, "Value": float(value), "Unit": "Count"})
    return data


def _resolve_client() -> MetricPublisher:
    """Return the provider-selected metric publisher (fail-closed on unknown provider)."""
    provider = str(getattr(settings, "CLOUD_PROVIDER", "")).lower()
    if provider == "aws":
        import boto3

        return boto3.client("cloudwatch")
    if provider == "gcp":
        return _GcpMonitoringPublisher()
    raise RuntimeError(f"unsupported CLOUD_PROVIDER for warm-pool metrics: {provider!r}")


def emit_gauges(snapshots: list[WarmPoolBucketSnapshot], *, client: MetricPublisher | None = None) -> bool:
    """Publish one pool-depth sample. Returns False (never raises) on any failure."""
    if not snapshots:
        return True
    try:
        publisher = client or _resolve_client()
        publisher.put_metric_data(Namespace=_namespace(), MetricData=build_gauge_metric_data(snapshots))
        return True
    except Exception as exc:
        logger.warning("warm-pool gauge emit failed: %s", safe_log_value(str(exc)))
        return False


def emit_claim_outcome(*, bucket_id: str, backend: str, outcome: str, client: MetricPublisher | None = None) -> bool:
    """Publish one claim-outcome counter (hit/fallback). Fail-soft.

    ``outcome`` must be a closed value; an unknown outcome is dropped rather than
    emitted, so a caller bug cannot introduce an unbounded dimension value.
    """
    if outcome not in _VALID_OUTCOMES:
        logger.warning("warm-pool claim outcome %r is not closed; dropping", safe_log_value(str(outcome)))
        return False
    try:
        publisher = client or _resolve_client()
        publisher.put_metric_data(
            Namespace=_namespace(),
            MetricData=[
                {
                    "MetricName": _CLAIM_OUTCOME,
                    "Dimensions": [
                        {"Name": "Bucket", "Value": bucket_id},
                        {"Name": "Backend", "Value": backend},
                        {"Name": "Outcome", "Value": outcome},
                    ],
                    "Value": 1.0,
                    "Unit": "Count",
                }
            ],
        )
        return True
    except Exception as exc:
        logger.warning("warm-pool claim-outcome emit failed: %s", safe_log_value(str(exc)))
        return False


class _GcpMonitoringPublisher:
    """``put_metric_data``-compatible Cloud Monitoring adapter for warm-pool metrics.

    Mirrors the portal-capacity GCP adapter's surface: it writes one gauge point per
    ``MetricData`` entry to a Cloud Monitoring custom metric type under the warm-pool
    namespace. google libs are imported lazily so the AWS path never loads them.
    """

    @staticmethod
    def put_metric_data(**kwargs: object) -> None:
        import time

        from google.cloud import monitoring_v3

        from shared.cloud.gcp.base import get_project_id

        project_id = get_project_id()
        project_name = f"projects/{project_id}"
        namespace = str(kwargs.get("Namespace", "Shifter/WarmPool")).strip("/").replace("/", ".").lower()
        metric_data: list[dict[str, Any]] = kwargs["MetricData"]  # type: ignore[assignment]
        now_seconds = int(time.time())
        client = monitoring_v3.MetricServiceClient()
        series: list[Any] = []
        for entry in metric_data:
            labels = {str(d["Name"]): str(d["Value"]) for d in entry.get("Dimensions", [])}
            ts = monitoring_v3.TimeSeries()
            ts.metric.type = f"custom.googleapis.com/{namespace}/{str(entry['MetricName']).lower()}"
            ts.metric.labels.update(labels)
            ts.resource.type = "global"
            ts.resource.labels["project_id"] = project_id
            point = monitoring_v3.Point(
                {
                    "interval": {"end_time": {"seconds": now_seconds}},
                    "value": {"double_value": float(entry["Value"])},
                }
            )
            ts.points = [point]
            series.append(ts)
        client.create_time_series(name=project_name, time_series=series)
