"""Operator metrics for the scoped-communication delivery engine (ADR-051-R12, #2098).

Mirrors the provider-aware, fail-soft pattern of ``shared.warm_pool.metrics``
(CloudWatch on AWS, Cloud Monitoring on GCP) in its own ``Shifter/CtfCommunication``
namespace, rather than importing ``config`` from CTF. Emission never raises: a
metrics outage can never change delivery truth.

Every dimension is a CLOSED, low-cardinality label -- outcome / channel / reason /
scope class -- never a recipient, user, participant, workspace, event, or range
identifier, and never message content. Bounded identifiers belong in authorized
audit evidence, not in metric labels.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from django.conf import settings
from django.db.models import Count, Min

from ctf.enums_communication import CommunicationChannel, DeliveryStatus
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from ctf.services.communication.delivery import DeliveryRunStats, NowFunc

logger = logging.getLogger(__name__)

_NAMESPACE_DEFAULT = "Shifter/CtfCommunication"

# Closed metric names.
_WORKER_OUTCOME = "WorkerOutcome"
_BACKLOG_DEPTH = "BacklogDepth"
_OLDEST_DUE_AGE = "OldestDueAgeSeconds"
_ADMISSION_DENIED = "AdmissionDenied"

# Closed dimension-value sets. A value outside the set is dropped, never emitted,
# so a caller bug can never introduce an unbounded dimension value.
_OUTCOMES = frozenset({"accepted", "retried", "expired", "failed", "suppressed", "stale", "reclaimed", "claimed"})
_CHANNELS = frozenset(c.value for c in CommunicationChannel)
_SCOPE_CLASSES = frozenset({"actor", "event", "workspace", "global"})

# Non-terminal statuses form the durable backlog (pending + in-flight work).
_BACKLOG_STATUSES = (
    DeliveryStatus.QUEUED.value,
    DeliveryStatus.RETRY_DUE.value,
    DeliveryStatus.CLAIMED.value,
)


class MetricPublisher(Protocol):
    """The ``put_metric_data(Namespace=..., MetricData=...)`` surface both providers expose."""

    def put_metric_data(self, **kwargs: object) -> object: ...


def _namespace() -> str:
    """Return the configured metrics namespace (default ``Shifter/CtfCommunication``)."""
    return getattr(settings, "CTF_COMMUNICATION_METRICS_NAMESPACE", _NAMESPACE_DEFAULT)


def _resolve_client() -> MetricPublisher:
    """Return the provider-selected metric publisher (fail-closed on unknown provider)."""
    provider = str(getattr(settings, "CLOUD_PROVIDER", "")).lower()
    if provider == "aws":
        import boto3

        return boto3.client("cloudwatch")
    if provider == "gcp":
        return _GcpMonitoringPublisher()
    raise RuntimeError(f"unsupported CLOUD_PROVIDER for communication metrics: {provider!r}")


def _publish(metric_data: list[dict[str, object]], *, client: MetricPublisher | None) -> bool:
    """Publish a batch of metric entries, fail-soft (never raises)."""
    if not metric_data:
        return True
    try:
        publisher = client or _resolve_client()
        publisher.put_metric_data(Namespace=_namespace(), MetricData=metric_data)
        return True
    # Observability is best-effort; a metrics outage never breaks delivery.
    except Exception as exc:
        logger.warning("ctf communication metric emit failed: %s", safe_log_value(str(exc)))
        return False


def _counter(name: str, dimensions: list[dict[str, str]], value: float) -> dict[str, object]:
    """Build one CloudWatch-shaped Count metric entry."""
    return {"MetricName": name, "Dimensions": dimensions, "Value": float(value), "Unit": "Count"}


def emit_worker_run(stats: DeliveryRunStats, *, now_func: NowFunc, client: MetricPublisher | None = None) -> bool:
    """Emit per-run worker outcome counters plus a fresh backlog sample."""
    data: list[dict[str, object]] = []
    counts = {
        "accepted": stats.accepted,
        "retried": stats.retried,
        "expired": stats.expired,
        "failed": stats.failed,
        "suppressed": stats.suppressed,
        "stale": stats.stale,
        "reclaimed": stats.reclaimed,
        "claimed": stats.claimed,
    }
    for outcome, count in counts.items():
        if count and outcome in _OUTCOMES:
            data.append(_counter(_WORKER_OUTCOME, [{"Name": "Outcome", "Value": outcome}], count))
    published = _publish(data, client=client)
    backlog = emit_backlog_gauges(now_func=now_func, client=client)
    return published and backlog


def emit_backlog_gauges(*, now_func: NowFunc, client: MetricPublisher | None = None) -> bool:
    """Emit per-channel backlog depth and the oldest due-command age (seconds)."""
    from ctf.models import DeliveryAttempt

    now = now_func()
    depth_rows = (
        DeliveryAttempt.objects.filter(status__in=_BACKLOG_STATUSES).values("channel").annotate(depth=Count("id"))
    )
    data: list[dict[str, object]] = []
    for row in depth_rows:
        channel = row["channel"]
        if channel in _CHANNELS:
            data.append(_counter(_BACKLOG_DEPTH, [{"Name": "Channel", "Value": channel}], row["depth"]))
    oldest = (
        DeliveryAttempt.objects.filter(
            status__in=(DeliveryStatus.QUEUED.value, DeliveryStatus.RETRY_DUE.value),
            due_at__lte=now,
        )
        .aggregate(oldest=Min("due_at"))
        .get("oldest")
    )
    age = (now - oldest).total_seconds() if oldest else 0.0
    data.append({"MetricName": _OLDEST_DUE_AGE, "Dimensions": [], "Value": float(max(age, 0.0)), "Unit": "Seconds"})
    return _publish(data, client=client)


def emit_admission_denied(*, scope_class: str, client: MetricPublisher | None = None) -> bool:
    """Emit one admission/backpressure denial counter for a closed scope class."""
    if scope_class not in _SCOPE_CLASSES:
        logger.warning("ctf communication denial scope %r is not closed; dropping", safe_log_value(scope_class))
        return False
    return _publish(
        [_counter(_ADMISSION_DENIED, [{"Name": "ScopeClass", "Value": scope_class}], 1)],
        client=client,
    )


class _GcpMonitoringPublisher:
    """``put_metric_data``-compatible Cloud Monitoring adapter (mirrors warm-pool's)."""

    @staticmethod
    def put_metric_data(**kwargs: object) -> None:
        import time

        from google.cloud import monitoring_v3

        from shared.cloud.gcp.base import get_project_id

        project_id = get_project_id()
        project_name = f"projects/{project_id}"
        namespace = str(kwargs.get("Namespace", _NAMESPACE_DEFAULT)).strip("/").replace("/", ".").lower()
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
