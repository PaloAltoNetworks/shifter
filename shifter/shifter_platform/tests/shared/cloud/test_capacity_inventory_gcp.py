"""GCP read-only capacity inventory (PLAT-201, #680).

Parity with the AWS adapter's defensive contract: validate shape, treat an
absent datapoint as unmeasured rather than idle, carry the provider's own
timestamp, and degrade instead of raising.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from shared.capacity import (
    CapacityMetricSpec,
    CapacityReasonCode,
    MeasurementSource,
    PartitionRef,
    ProviderMetricRef,
)
from shared.cloud.gcp.capacity_inventory import GCPCapacityInventory

OBSERVED_AT = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def _partition(project: str = "shifter-dev") -> PartitionRef:
    return PartitionRef(
        name="gcp-dev-usc1",
        provider="gcp",
        account=project,
        region="us-central1",
        backend="gce",
        policy_profile="default",
    )


def _spec(**overrides: object) -> CapacityMetricSpec:
    defaults: dict[str, object] = {
        "name": "gce_cpus",
        "dimension": "vcpu",
        "unit": "count",
        "partition": "gcp-dev-usc1",
        "source": MeasurementSource.PROVIDER_PROBE,
        "freshness_seconds": 900,
        "provider_ref": ProviderMetricRef(
            limit_ref="serviceruntime.googleapis.com/quota/limit",
            usage_ref="serviceruntime.googleapis.com/quota/allocation/usage",
        ),
    }
    defaults.update(overrides)
    return CapacityMetricSpec(**defaults)  # type: ignore[arg-type]


class FakeSeries:
    """One Cloud Monitoring time series with a single point."""

    def __init__(self, value: object, when: datetime | None):
        self.value = value
        self.when = when


class FakeMonitoringClient:
    """Stands in for the Cloud Monitoring time-series client."""

    def __init__(self, limit_series=None, usage_series=None, error: Exception | None = None):
        self._limit = limit_series if limit_series is not None else [FakeSeries(1024.0, OBSERVED_AT)]
        self._usage = usage_series if usage_series is not None else [FakeSeries(256.0, OBSERVED_AT)]
        self._error = error
        self.queries: list[str] = []

    def list_time_series(self, *, metric_type: str, project: str, region: str):
        self.queries.append(metric_type)
        if self._error is not None:
            raise self._error
        return self._limit if metric_type.endswith("/limit") else self._usage


def _inventory(client: FakeMonitoringClient) -> GCPCapacityInventory:
    return GCPCapacityInventory(monitoring_client=client)


class TestObservationHappyPath:
    def test_reads_limit_and_usage(self):
        result = _inventory(FakeMonitoringClient()).observe(_spec(), _partition())

        assert result.reason_code is None
        assert result.observation is not None
        assert result.observation.limit == 1024.0
        assert result.observation.usage == 256.0
        assert result.observation.source is MeasurementSource.PROVIDER_PROBE

    def test_observed_at_is_the_datapoint_timestamp(self):
        stamped = OBSERVED_AT - timedelta(minutes=20)
        client = FakeMonitoringClient(usage_series=[FakeSeries(8.0, stamped)])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is not None
        assert result.observation.observed_at == stamped

    def test_queries_target_the_spec_metric_types(self):
        client = FakeMonitoringClient()

        _inventory(client).observe(_spec(), _partition())

        assert "serviceruntime.googleapis.com/quota/limit" in client.queries
        assert "serviceruntime.googleapis.com/quota/allocation/usage" in client.queries


class TestShapeValidation:
    @pytest.mark.parametrize("series", [[], [FakeSeries(None, OBSERVED_AT)], [FakeSeries("x", OBSERVED_AT)]])
    def test_malformed_limit_series_is_unavailable(self, series):
        client = FakeMonitoringClient(limit_series=series)

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    def test_absent_usage_point_is_unmeasured_not_zero(self):
        client = FakeMonitoringClient(usage_series=[])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    def test_missing_timestamp_is_unavailable(self):
        client = FakeMonitoringClient(usage_series=[FakeSeries(4.0, None)])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is None


class TestFailureHandling:
    def test_client_error_degrades_rather_than_raises(self):
        client = FakeMonitoringClient(error=RuntimeError("permission denied on project"))

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    def test_metric_without_coordinates_is_unsupported(self):
        result = _inventory(FakeMonitoringClient()).observe(_spec(provider_ref=None), _partition())

        assert result.reason_code is CapacityReasonCode.METRIC_UNSUPPORTED

    def test_provider_error_text_is_not_logged(self, caplog):
        client = FakeMonitoringClient(error=RuntimeError("project shifter-secret-1234 denied"))

        with caplog.at_level("DEBUG"):
            _inventory(client).observe(_spec(), _partition())

        assert "shifter-secret-1234" not in caplog.text


class FakeInterval:
    def __init__(self, end_time):
        self.end_time = end_time


class FakeTypedValue:
    def __init__(self, int64_value=None, double_value=None):
        self.int64_value = int64_value
        self.double_value = double_value


class FakePoint:
    def __init__(self, value, end_time):
        self.value = value
        self.interval = FakeInterval(end_time)


class FakeProtobufSeries:
    """Shaped like a real Cloud Monitoring ``TimeSeries``."""

    def __init__(self, points):
        self.points = points


class TestProtobufSeriesShape:
    """The real API returns protobufs, not the flat shape the other tests use."""

    def test_int64_point_is_read(self):
        series = FakeProtobufSeries([FakePoint(FakeTypedValue(int64_value=64), OBSERVED_AT)])
        client = FakeMonitoringClient(limit_series=[series], usage_series=[series])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is not None
        assert result.observation.limit == 64.0

    def test_double_point_is_read(self):
        series = FakeProtobufSeries([FakePoint(FakeTypedValue(double_value=12.5), OBSERVED_AT)])
        client = FakeMonitoringClient(limit_series=[series], usage_series=[series])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is not None
        assert result.observation.usage == 12.5

    def test_series_without_points_is_unmeasured(self):
        client = FakeMonitoringClient(limit_series=[FakeProtobufSeries([])])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is None

    def test_point_without_a_timestamp_is_unmeasured(self):
        series = FakeProtobufSeries([FakePoint(FakeTypedValue(int64_value=8), None)])
        client = FakeMonitoringClient(limit_series=[series], usage_series=[series])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is None

    def test_negative_point_is_rejected(self):
        """A negative limit is malformed, not a very small quota."""
        series = FakeProtobufSeries([FakePoint(FakeTypedValue(double_value=-3.0), OBSERVED_AT)])
        client = FakeMonitoringClient(limit_series=[series], usage_series=[series])

        result = _inventory(client).observe(_spec(), _partition())

        assert result.observation is None

    def test_non_list_response_is_unmeasured(self):
        class OddClient:
            def list_time_series(self, *, metric_type, project, region):
                return "not-a-list"

        result = _inventory(OddClient()).observe(_spec(), _partition())

        assert result.observation is None
