"""Portal web capacity metrics emitter (``Shifter/PortalCapacity``, issue #940).

The portal autoscaling problem is request-path saturation that average EC2 CPU
does not reflect (issue #851 / #940). ALB-native metrics
(``RequestCountPerTarget`` / ``TargetResponseTime``) drive the ASG scaling
policies; this module adds the *app-side* saturation signals that those metrics
cannot see from outside the process: how busy each portal web worker is and how
full its terminal-session budget is.

Design contract (see
``docs/architecture/portal-app-saturation-autoscaling-preflight-940.md``):

- Signals live in their own ``Shifter/PortalCapacity`` namespace, never
  ``Shifter/WorkerHealth`` (that namespace is worker-container liveness).
- Every signal is per *process*. The portal runs Gunicorn with
  ``PORTAL_WEB_WORKERS`` Uvicorn workers (``entrypoint.sh``, #174), so each
  worker imports this module once and emits its own gauges under a single
  low-cardinality ``NamePrefix`` dimension. Fleet aggregation is a CloudWatch
  statistic choice, documented per metric:
  - ``WorkerBusyRatio`` / ``TerminalSessionUtilization`` are ratios: ``Average``
    is the fleet mean, ``Maximum`` is the hottest worker.
  - ``WorkerInFlightRequests`` / ``TerminalActiveSessions`` are counts: with the
    publish interval aligned to the metric period, ``Sum`` approximates the
    fleet total. The terminal fleet denominator is
    ``in-service instances * PORTAL_WEB_WORKERS * TERMINAL_MAX_SESSIONS``.
- ``WorkerBusyRatio`` is in-flight HTTP request concurrency divided by a
  configured soft-concurrency target. It is a backpressure *proxy*, explicitly
  not an OS pre-middleware accept-queue depth, and is named accordingly.
- Emission is fail-soft: a CloudWatch outage, throttle, or boot-time gap logs a
  bounded, sanitized line and never raises into request serving. These signals
  feed observability and an additive, fail-safe scale-*out* alarm only; they are
  never a scale-in input, so missing data cannot scale in a saturated fleet.
- The emitter never shells out, never reads request bodies or terminal streams,
  and never labels a metric with anything but the environment ``NamePrefix``.
- Provider-aware publishing (PLAT-002, #671): AWS writes to CloudWatch via
  boto3; GCP writes the same gauges to Cloud Monitoring via the adapter in
  ``config/capacity_metrics_gcp.py``, selected by ``CLOUD_PROVIDER``. The
  emitter itself is provider-agnostic — it always builds the same MetricData
  and calls ``put_metric_data`` on whichever client the factory returned.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from shared.log_sanitize import safe_log_value

_logger = logging.getLogger(__name__)

NAMESPACE = "Shifter/PortalCapacity"


class InFlightCounter:
    """Thread-safe process-local gauge of in-flight HTTP requests.

    ``RequestInFlightMiddleware`` brackets every HTTP request with
    ``increment()`` / ``decrement()``. The emitter thread reads ``current()``.
    A lock guards the integer because the portal serves requests on the event
    loop while Django may also run sync middleware in a threadpool, so mutation
    and reads can race across threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def increment(self) -> None:
        with self._lock:
            self._value += 1

    def decrement(self) -> None:
        with self._lock:
            # Floor at zero: a decrement without a matching increment (e.g. an
            # error before the increment ran) must never drive the gauge below 0.
            if self._value > 0:
                self._value -= 1

    def current(self) -> int:
        with self._lock:
            return self._value

    def reset(self) -> None:
        """Zero the counter. Test-only; production never resets a live gauge."""
        with self._lock:
            self._value = 0


# One counter per worker process, shared by the middleware and the emitter.
inflight_requests = InFlightCounter()


@dataclass(frozen=True)
class CapacitySnapshot:
    """A single process's capacity reading at one instant."""

    in_flight_requests: int
    worker_busy_ratio: float
    terminal_active_sessions: int
    terminal_session_utilization: float


def _ratio(numerator: int, denominator: int) -> float:
    """Safe ratio; a non-positive denominator (misconfig) yields 0.0, not a crash."""
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def compute_snapshot(
    *,
    in_flight: int,
    terminal_active: int,
    soft_concurrency: int,
    terminal_max_sessions: int,
) -> CapacitySnapshot:
    """Pure snapshot builder. No globals, no I/O — directly unit-testable."""
    return CapacitySnapshot(
        in_flight_requests=in_flight,
        worker_busy_ratio=_ratio(in_flight, soft_concurrency),
        terminal_active_sessions=terminal_active,
        terminal_session_utilization=_ratio(terminal_active, terminal_max_sessions),
    )


def collect_snapshot(soft_concurrency: int, terminal_max_sessions: int) -> CapacitySnapshot:
    """Read this process's live gauges and compute the capacity snapshot.

    ``session_registry`` is imported lazily so importing this module (done at
    middleware-stack build time) never forces the mission_control app to load
    earlier than Django arranges it.
    """
    from mission_control.terminal_sessions import session_registry

    terminal = session_registry.snapshot().get("active_sessions", 0)
    return compute_snapshot(
        in_flight=inflight_requests.current(),
        terminal_active=terminal,
        soft_concurrency=soft_concurrency,
        terminal_max_sessions=terminal_max_sessions,
    )


def build_metric_data(snapshot: CapacitySnapshot, name_prefix: str) -> list[dict[str, object]]:
    """Translate a snapshot into CloudWatch ``MetricData`` entries.

    Every entry carries exactly one dimension (``NamePrefix``) so the series
    stays low-cardinality and cheap to alarm on. Ratios use ``None`` units
    (dimensionless gauges); counts use ``Count``.
    """
    dimensions = [{"Name": "NamePrefix", "Value": name_prefix}]
    return [
        {
            "MetricName": "WorkerInFlightRequests",
            "Value": float(snapshot.in_flight_requests),
            "Unit": "Count",
            "Dimensions": dimensions,
        },
        {
            "MetricName": "WorkerBusyRatio",
            "Value": float(snapshot.worker_busy_ratio),
            "Unit": "None",
            "Dimensions": dimensions,
        },
        {
            "MetricName": "TerminalActiveSessions",
            "Value": float(snapshot.terminal_active_sessions),
            "Unit": "Count",
            "Dimensions": dimensions,
        },
        {
            "MetricName": "TerminalSessionUtilization",
            "Value": float(snapshot.terminal_session_utilization),
            "Unit": "None",
            "Dimensions": dimensions,
        },
    ]


class _CloudWatchClient(Protocol):
    """Minimal metrics-client surface the emitter calls. The emitter invokes
    ``put_metric_data(Namespace=..., MetricData=...)`` (the boto3 CloudWatch
    surface); the GCP Cloud Monitoring adapter mirrors that dynamic surface so
    the emitter never branches on provider."""

    def put_metric_data(self, **kwargs: object) -> object: ...


SnapshotCollector = Callable[[int, int], CapacitySnapshot]


class PortalCapacityEmitter:
    """Periodically publish this worker's capacity gauges to CloudWatch.

    Runs as a daemon thread, one per worker process, started from
    ``config.asgi``. The thread is decoupled from the event loop so the
    (synchronous) boto3 ``put_metric_data`` call never blocks request handling.
    """

    def __init__(
        self,
        *,
        client: _CloudWatchClient,
        name_prefix: str,
        interval_seconds: int,
        soft_concurrency: int,
        terminal_max_sessions: int,
        collector: SnapshotCollector = collect_snapshot,
    ) -> None:
        self._client = client
        self._name_prefix = name_prefix
        self._interval_seconds = interval_seconds
        self._soft_concurrency = soft_concurrency
        self._terminal_max_sessions = terminal_max_sessions
        self._collector = collector
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def emit_once(self) -> bool:
        """Publish one sample. Returns False (never raises) on any failure."""
        try:
            snapshot = self._collector(self._soft_concurrency, self._terminal_max_sessions)
            self._client.put_metric_data(
                Namespace=NAMESPACE,
                MetricData=build_metric_data(snapshot, self._name_prefix),
            )
            return True
        except Exception as exc:
            # Fail-soft: a metric blip must not break request serving.
            _logger.warning("portal-capacity metric emit failed: %s", safe_log_value(str(exc)))
            return False

    def _run(self) -> None:
        # Emit immediately, then on the interval until stopped. ``Event.wait``
        # returns True when set, so a stop request breaks the loop promptly.
        while not self._stop.is_set():
            self.emit_once()
            if self._stop.wait(self._interval_seconds):
                break

    def start(self) -> None:
        if self._thread is not None:
            return
        thread = threading.Thread(target=self._run, name="portal-capacity-emitter", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()


def _default_client_factory() -> _CloudWatchClient:
    """Construct the real CloudWatch client. boto3 is lazy so non-AWS runtimes
    (local dev, pytest) never import it."""
    import boto3

    return boto3.client("cloudwatch")


def _resolve_default_client_factory() -> Callable[[], _CloudWatchClient]:
    """Pick the per-provider metrics client factory from ``CLOUD_PROVIDER`` (PLAT-002, #671).

    GCP publishes the same gauges to Cloud Monitoring through a
    ``put_metric_data``-compatible adapter; google libs are imported lazily by
    the factory so the AWS path never loads them. Any other provider keeps the
    CloudWatch (boto3) factory.
    """
    from django.conf import settings

    provider = str(getattr(settings, "CLOUD_PROVIDER", "aws")).lower()
    if provider == "gcp":
        from config.capacity_metrics_gcp import build_gcp_client_factory

        return build_gcp_client_factory()
    return _default_client_factory


def build_emitter_from_config(
    *,
    enabled: bool,
    name_prefix: str,
    interval_seconds: int,
    soft_concurrency: int,
    terminal_max_sessions: int,
    client_factory: Callable[[], _CloudWatchClient] | None = None,
    collector: SnapshotCollector = collect_snapshot,
) -> PortalCapacityEmitter | None:
    """Build and start a per-worker emitter, or return ``None`` when it must not run.

    The metrics client is provider-aware: AWS publishes to CloudWatch (boto3),
    GCP to Cloud Monitoring, selected from ``settings.CLOUD_PROVIDER`` unless an
    explicit ``client_factory`` is injected (tests). Returns ``None`` (logging a
    bounded reason) and never raises when metrics are disabled, the
    ``NamePrefix`` dimension is missing, or the client cannot be constructed —
    worker boot must never fail because of an optional observability signal.
    """
    if client_factory is None:
        client_factory = _resolve_default_client_factory()
    # Refuse to start (logging a bounded reason) rather than raise: an optional
    # observability signal must never fail worker boot. Disabled is silent; an
    # enabled-but-unlabelled emitter is an error because its series could not
    # match the CloudWatch alarms/dashboard.
    if not enabled or not name_prefix:
        if enabled:
            _logger.error(
                "portal-capacity metrics enabled but PORTAL_CAPACITY_NAME_PREFIX is empty; emitter not started"
            )
        return None
    try:
        client = client_factory()
    except Exception as exc:
        # Fail-soft: never break worker boot on a client-init error. Log a bounded,
        # sanitized message, not the traceback (raw exception text is forbidden by
        # the #940 preflight anti-patterns).
        _logger.warning("portal-capacity metrics: client init failed: %s", safe_log_value(str(exc)))
        return None
    emitter = PortalCapacityEmitter(
        client=client,
        name_prefix=name_prefix,
        interval_seconds=interval_seconds,
        soft_concurrency=soft_concurrency,
        terminal_max_sessions=terminal_max_sessions,
        collector=collector,
    )
    emitter.start()
    _logger.info(
        "portal-capacity emitter started (name_prefix=%s interval=%ss soft_concurrency=%s)",
        safe_log_value(name_prefix),
        interval_seconds,
        soft_concurrency,
    )
    return emitter
