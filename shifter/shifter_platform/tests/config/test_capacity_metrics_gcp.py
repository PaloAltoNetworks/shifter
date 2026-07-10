"""Tests for the GCP Cloud Monitoring adapter of the portal capacity emitter
(PLAT-002, #671).

The adapter translates the provider-neutral CloudWatch-shaped MetricData the
emitter produces into Cloud Monitoring TimeSeries mappings and writes them via
create_time_series, so a GCP deployment publishes the same Shifter/PortalCapacity
gauges AWS publishes to CloudWatch. These cover the pure translation and the
fail-soft write path with a fake monitoring client; no google libs or network.
"""

from __future__ import annotations

from config import capacity_metrics
from config.capacity_metrics_gcp import GCPMonitoringClient, build_time_series

NAME_PREFIX = "dev-portal"
PROJECT = "shifter-gcp-dev"
TS = 1_700_000_000


def _metric_data() -> list[dict]:
    snap = capacity_metrics.compute_snapshot(
        in_flight=3, terminal_active=2, soft_concurrency=6, terminal_max_sessions=8
    )
    return capacity_metrics.build_metric_data(snap, NAME_PREFIX)


# ---------------------------------------------------------------------------
# build_time_series — pure translation
# ---------------------------------------------------------------------------


def test_build_time_series_maps_every_metric_to_a_custom_series():
    series = build_time_series(_metric_data(), project_id=PROJECT, timestamp_seconds=TS)

    # One series per CloudWatch MetricData entry (the four capacity gauges).
    assert len(series) == 4
    types = {s["metric"]["type"] for s in series}
    assert types == {
        "custom.googleapis.com/shifter/portal_capacity/WorkerInFlightRequests",
        "custom.googleapis.com/shifter/portal_capacity/WorkerBusyRatio",
        "custom.googleapis.com/shifter/portal_capacity/TerminalActiveSessions",
        "custom.googleapis.com/shifter/portal_capacity/TerminalSessionUtilization",
    }


def test_build_time_series_carries_name_prefix_label_and_global_resource():
    series = build_time_series(_metric_data(), project_id=PROJECT, timestamp_seconds=TS)

    one = series[0]
    # The CloudWatch NamePrefix dimension becomes a low-cardinality metric label.
    assert one["metric"]["labels"] == {"name_prefix": NAME_PREFIX}
    # Custom metrics ride on the project-scoped global resource.
    assert one["resource"] == {"type": "global", "labels": {"project_id": PROJECT}}


def test_build_time_series_point_carries_value_and_timestamp():
    series = build_time_series(_metric_data(), project_id=PROJECT, timestamp_seconds=TS)
    by_type = {s["metric"]["type"].rsplit("/", 1)[1]: s for s in series}

    inflight = by_type["WorkerInFlightRequests"]["points"][0]
    assert inflight["value"] == {"double_value": 3.0}
    assert inflight["interval"] == {"end_time": {"seconds": TS}}
    # Ratio gauge: 3 in-flight / soft-concurrency 6 = 0.5.
    assert by_type["WorkerBusyRatio"]["points"][0]["value"] == {"double_value": 0.5}


def test_build_time_series_omits_descriptor_fields_unsettable_on_write():
    # metric_kind / value_type belong to the metric descriptor and must not be set
    # on a written TimeSeries (the API rejects it for auto-created custom metrics).
    series = build_time_series(_metric_data(), project_id=PROJECT, timestamp_seconds=TS)
    for s in series:
        assert "metric_kind" not in s
        assert "value_type" not in s


# ---------------------------------------------------------------------------
# GCPMonitoringClient.put_metric_data — write path
# ---------------------------------------------------------------------------


class _FakeMonitoringClient:
    """Records create_time_series calls; optionally raises to drive the fail path."""

    def __init__(self, raises: Exception | None = None) -> None:
        self._raises = raises
        self.calls: list[dict] = []

    def create_time_series(self, *, name, time_series):
        if self._raises is not None:
            raise self._raises
        self.calls.append({"name": name, "time_series": time_series})


def test_put_metric_data_writes_translated_series_to_project():
    fake = _FakeMonitoringClient()
    client = GCPMonitoringClient(client=fake, project_id=PROJECT, now=lambda: TS)

    client.put_metric_data(Namespace=capacity_metrics.NAMESPACE, MetricData=_metric_data())

    assert len(fake.calls) == 1
    assert fake.calls[0]["name"] == f"projects/{PROJECT}"
    assert len(fake.calls[0]["time_series"]) == 4


def test_emitter_publishes_through_gcp_client_adapter():
    # The provider-agnostic emitter drives the GCP adapter exactly as it drives
    # the boto3 CloudWatch client.
    fake = _FakeMonitoringClient()
    gcp_client = GCPMonitoringClient(client=fake, project_id=PROJECT, now=lambda: TS)
    emitter = capacity_metrics.PortalCapacityEmitter(
        client=gcp_client,
        name_prefix=NAME_PREFIX,
        interval_seconds=60,
        soft_concurrency=6,
        terminal_max_sessions=8,
        collector=lambda *_: capacity_metrics.compute_snapshot(
            in_flight=1, terminal_active=0, soft_concurrency=6, terminal_max_sessions=8
        ),
    )

    assert emitter.emit_once() is True
    assert len(fake.calls) == 1


def test_emitter_is_fail_soft_when_monitoring_write_raises():
    fake = _FakeMonitoringClient(raises=RuntimeError("monitoring down"))
    gcp_client = GCPMonitoringClient(client=fake, project_id=PROJECT, now=lambda: TS)
    emitter = capacity_metrics.PortalCapacityEmitter(
        client=gcp_client,
        name_prefix=NAME_PREFIX,
        interval_seconds=60,
        soft_concurrency=6,
        terminal_max_sessions=8,
        collector=lambda *_: capacity_metrics.compute_snapshot(
            in_flight=1, terminal_active=0, soft_concurrency=6, terminal_max_sessions=8
        ),
    )

    assert emitter.emit_once() is False


# ---------------------------------------------------------------------------
# Provider selection in build_emitter_from_config
# ---------------------------------------------------------------------------


def test_resolve_default_client_factory_selects_by_provider(monkeypatch):
    # The provider routing is what production relies on (asgi calls
    # build_emitter_from_config with no explicit factory; the resolver reads
    # CLOUD_PROVIDER from settings). AWS keeps the boto3 factory; GCP returns a
    # distinct closure that builds a Cloud Monitoring client.
    from django.conf import settings as django_settings

    monkeypatch.setattr(django_settings, "CLOUD_PROVIDER", "aws")
    assert capacity_metrics._resolve_default_client_factory() is capacity_metrics._default_client_factory

    monkeypatch.setattr(django_settings, "CLOUD_PROVIDER", "GCP")
    gcp_factory = capacity_metrics._resolve_default_client_factory()
    assert gcp_factory is not capacity_metrics._default_client_factory
    assert callable(gcp_factory)


def test_build_emitter_with_no_factory_routes_through_provider_resolution(monkeypatch):
    # With client_factory=None (the production call shape), the builder MUST go
    # through _resolve_default_client_factory(). Patch that seam so the routing
    # branch is actually exercised — a regression that ignored it would fail here.
    fake = _FakeMonitoringClient()
    resolver_calls = []
    built_clients = []

    def fake_resolver():
        resolver_calls.append(True)

        def _factory():
            client = GCPMonitoringClient(client=fake, project_id=PROJECT, now=lambda: TS)
            built_clients.append(client)
            return client

        return _factory

    monkeypatch.setattr(capacity_metrics, "_resolve_default_client_factory", fake_resolver)

    emitter = capacity_metrics.build_emitter_from_config(
        enabled=True,
        name_prefix=NAME_PREFIX,
        interval_seconds=60,
        soft_concurrency=6,
        terminal_max_sessions=8,
        client_factory=None,
        collector=lambda *_: capacity_metrics.compute_snapshot(
            in_flight=0, terminal_active=0, soft_concurrency=6, terminal_max_sessions=8
        ),
    )
    try:
        # The builder routed through the provider resolver and used the client it
        # produced. (The started daemon emits asynchronously, so the call count is
        # not asserted here — see the write-path tests for that.)
        assert emitter is not None
        assert resolver_calls == [True]
        assert len(built_clients) == 1
    finally:
        if emitter is not None:
            emitter.stop()


def test_build_emitter_honors_explicitly_injected_factory():
    # An explicit client_factory overrides provider resolution (the test seam).
    fake = _FakeMonitoringClient()
    built = []

    def explicit_factory():
        client = GCPMonitoringClient(client=fake, project_id=PROJECT, now=lambda: TS)
        built.append(client)
        return client

    emitter = capacity_metrics.build_emitter_from_config(
        enabled=True,
        name_prefix=NAME_PREFIX,
        interval_seconds=60,
        soft_concurrency=6,
        terminal_max_sessions=8,
        client_factory=explicit_factory,
        collector=lambda *_: capacity_metrics.compute_snapshot(
            in_flight=0, terminal_active=0, soft_concurrency=6, terminal_max_sessions=8
        ),
    )
    try:
        assert emitter is not None
        assert len(built) == 1
    finally:
        if emitter is not None:
            emitter.stop()
