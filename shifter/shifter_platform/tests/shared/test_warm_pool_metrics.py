"""Tests for ``shared.warm_pool.metrics`` (#28).

Pins the observable contract: gauge/counter shape in the WarmPool namespace,
strictly low-cardinality dimensions (no user/request/scenario ids), closed claim
outcomes, and fail-soft emission (an observability blip never raises).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.warm_pool.metrics import (
    CLAIM_FALLBACK,
    CLAIM_HIT,
    WarmPoolBucketSnapshot,
    _GcpMonitoringPublisher,
    _resolve_client,
    build_gauge_metric_data,
    emit_claim_outcome,
    emit_gauges,
)


class _FakeClient:
    def __init__(self, *, boom: bool = False):
        self.calls: list[dict] = []
        self._boom = boom

    def put_metric_data(self, **kwargs):
        if self._boom:
            raise RuntimeError("cloud blip")
        self.calls.append(kwargs)


_SNAP = WarmPoolBucketSnapshot(
    bucket_id="gce-polaris", backend="gce", region="us-central1", ready=2, provisioning=1, unhealthy=0, claimed=3
)

_ALLOWED_DIMENSIONS = {"Bucket", "Backend", "Region", "Outcome"}


class TestGauges:
    def test_metric_data_shape_and_low_cardinality(self):
        data = build_gauge_metric_data([_SNAP])
        names = {d["MetricName"] for d in data}
        assert names == {"WarmPoolReady", "WarmPoolProvisioning", "WarmPoolUnhealthy", "WarmPoolClaimed"}
        for entry in data:
            assert entry["Unit"] == "Count"
            for dim in entry["Dimensions"]:
                assert dim["Name"] in _ALLOWED_DIMENSIONS

    def test_emit_gauges_uses_warm_pool_namespace(self):
        client = _FakeClient()
        assert emit_gauges([_SNAP], client=client) is True
        assert client.calls[0]["Namespace"] == "Shifter/WarmPool"

    def test_empty_snapshots_is_noop(self):
        client = _FakeClient()
        assert emit_gauges([], client=client) is True
        assert client.calls == []

    def test_emit_is_fail_soft(self):
        assert emit_gauges([_SNAP], client=_FakeClient(boom=True)) is False


class TestClaimOutcome:
    @pytest.mark.parametrize("outcome", [CLAIM_HIT, CLAIM_FALLBACK])
    def test_closed_outcomes_emit(self, outcome):
        client = _FakeClient()
        assert emit_claim_outcome(bucket_id="b", backend="gce", outcome=outcome, client=client) is True
        entry = client.calls[0]["MetricData"][0]
        assert entry["MetricName"] == "WarmPoolClaimOutcome"
        assert {d["Name"] for d in entry["Dimensions"]} <= _ALLOWED_DIMENSIONS

    def test_unknown_outcome_dropped(self):
        client = _FakeClient()
        assert emit_claim_outcome(bucket_id="b", backend="gce", outcome="weird", client=client) is False
        assert client.calls == []

    def test_fail_soft(self):
        assert (
            emit_claim_outcome(bucket_id="b", backend="gce", outcome=CLAIM_HIT, client=_FakeClient(boom=True)) is False
        )


class TestResolveClient:
    def test_aws_returns_cloudwatch_client(self, monkeypatch):
        import boto3
        from django.conf import settings

        monkeypatch.setattr(settings, "CLOUD_PROVIDER", "aws", raising=False)
        monkeypatch.setattr(boto3, "client", lambda name: SimpleNamespace(kind=name))
        client = _resolve_client()
        assert client.kind == "cloudwatch"

    def test_gcp_returns_monitoring_publisher(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp", raising=False)
        assert isinstance(_resolve_client(), _GcpMonitoringPublisher)

    def test_unsupported_provider_raises(self, monkeypatch):
        from django.conf import settings

        monkeypatch.setattr(settings, "CLOUD_PROVIDER", "azure", raising=False)
        with pytest.raises(RuntimeError):
            _resolve_client()

    def test_emit_gauges_resolves_client_when_none(self, monkeypatch):
        import boto3
        from django.conf import settings

        seen: list = []
        monkeypatch.setattr(settings, "CLOUD_PROVIDER", "aws", raising=False)
        monkeypatch.setattr(
            boto3,
            "client",
            lambda name: SimpleNamespace(put_metric_data=lambda **kw: seen.append(kw)),
        )
        assert emit_gauges([_SNAP]) is True
        assert seen
        assert seen[0]["Namespace"] == "Shifter/WarmPool"


class _FakeLabels(dict):
    """A dict that also supports attribute-free ``.update`` (dict already does)."""


class _FakeMetric:
    def __init__(self):
        self.type = None
        self.labels = _FakeLabels()


class _FakeResource:
    def __init__(self):
        self.type = None
        self.labels = _FakeLabels()


class _FakeTimeSeries:
    def __init__(self):
        self.metric = _FakeMetric()
        self.resource = _FakeResource()
        self.points: list = []


class _FakeMonitoringClient:
    created: tuple | None = None

    def create_time_series(self, *, name, time_series):
        type(self).created = (name, list(time_series))


class TestGcpPublisher:
    def test_put_metric_data_builds_time_series(self, monkeypatch):
        # Patch the real ``monitoring_v3`` module's attributes rather than injecting a
        # fake via sys.modules: ``from google.cloud import monitoring_v3`` binds the
        # already-imported real submodule (present in CI), so a sys.modules override is
        # ignored once the package attribute exists. importorskip guards the rare env
        # where the google client library is absent.
        monitoring = pytest.importorskip("google.cloud.monitoring_v3")
        monkeypatch.setattr(monitoring, "MetricServiceClient", _FakeMonitoringClient)
        monkeypatch.setattr(monitoring, "TimeSeries", _FakeTimeSeries)
        monkeypatch.setattr(monitoring, "Point", lambda payload: payload)
        monkeypatch.setattr("shared.cloud.gcp.base.get_project_id", lambda: "proj-1", raising=False)
        monkeypatch.setattr(_FakeMonitoringClient, "created", None)

        publisher = _GcpMonitoringPublisher()
        publisher.put_metric_data(
            Namespace="Shifter/WarmPool",
            MetricData=build_gauge_metric_data([_SNAP]),
        )
        name, series = _FakeMonitoringClient.created
        assert name == "projects/proj-1"
        assert len(series) == 4  # one point per gauge metric
        assert series[0].metric.type.startswith("custom.googleapis.com/shifter.warmpool/")
        assert series[0].resource.labels["project_id"] == "proj-1"
