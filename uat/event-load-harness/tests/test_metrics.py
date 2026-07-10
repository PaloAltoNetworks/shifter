"""Metrics adapters: client-only is honest about gaps; AWS never fabricates."""

import datetime as dt

from event_load_harness.metrics import build_adapter
from event_load_harness.metrics.aws import AwsMetricsAdapter, _aggregate, _connection_churn_proxy
from event_load_harness.metrics.base import MetricsResult, MetricValue
from event_load_harness.metrics.client_only import ClientOnlyAdapter

WINDOW = ("2026-06-14T00:00:00Z", "2026-06-14T00:05:00Z")
START = dt.datetime(2026, 6, 14, 0, 0, tzinfo=dt.UTC)


def test_client_only_adapter_reports_explicit_gaps():
    adapter = ClientOnlyAdapter()
    result = adapter.collect(*WINDOW)
    assert isinstance(result, MetricsResult)
    assert result.provider == "client-only"
    assert result.metrics == {}
    # the provider signals it did NOT collect are named, not silently dropped
    joined = " ".join(result.gaps).lower()
    assert "alb" in joined
    assert "rds" in joined
    assert "redis" in joined


def test_build_adapter_selects_client_only_by_default():
    adapter = build_adapter("client-only", region=None, targets={})
    assert adapter.provider == "client-only"


def test_build_adapter_selects_aws():
    adapter = build_adapter("aws", region="us-east-2", targets={})
    assert adapter.provider == "aws"


def test_aws_adapter_with_no_targets_returns_gaps_without_calling_cloud():
    # No resource identifiers configured => every signal is a gap, and crucially
    # no boto3/CloudWatch call is attempted (client is never constructed).
    adapter = AwsMetricsAdapter(region="us-east-2", targets={})
    result = adapter.collect(*WINDOW)
    assert result.provider == "aws"
    assert result.metrics == {}
    assert result.gaps  # all signals unavailable
    assert adapter._client_constructed is False


def test_aggregate_is_statistic_specific_across_all_datapoints():
    # Counts sum across the run window; percentiles take the worst tail; averages mean.
    assert _aggregate("Sum", [10.0, 5.0, 2.0]) == 17.0
    assert _aggregate("p95", [120.0, 300.0, 200.0]) == 300.0
    assert _aggregate("Maximum", [12.0, 9.0, 20.0]) == 20.0
    assert _aggregate("Average", [2.0, 4.0]) == 3.0
    assert _aggregate("Sum", []) is None


class _FakeCloudWatch:
    """Records get_metric_statistics kwargs and returns two-period datapoints."""

    def __init__(self):
        self.calls = []

    def get_metric_statistics(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "Datapoints": [
                {
                    "Timestamp": START,
                    "Sum": 3.0,
                    "Average": 10.0,
                    "Maximum": 15.0,
                    "ExtendedStatistics": {"p95": 100.0, "p99": 150.0},
                },
                {
                    "Timestamp": START + dt.timedelta(minutes=5),
                    "Sum": 4.0,
                    "Average": 20.0,
                    "Maximum": 25.0,
                    "ExtendedStatistics": {"p95": 250.0, "p99": 300.0},
                },
            ]
        }


def test_aws_percentile_request_uses_extended_statistics_only():
    fake = _FakeCloudWatch()
    adapter = AwsMetricsAdapter(region="us-east-2", targets={"alb": "app/portal/abc"}, client=fake)
    result = adapter.collect(*WINDOW)
    # The ALB p95 (TargetResponseTime) call must use ExtendedStatistics and not Statistics,
    # or CloudWatch rejects it and the signal silently becomes a gap.
    pct_calls = [c for c in fake.calls if c["MetricName"] == "TargetResponseTime"]
    assert pct_calls and "ExtendedStatistics" in pct_calls[0] and "Statistics" not in pct_calls[0]
    # p95 aggregates to the worst tail across both periods.
    assert result.metrics["alb.targetresponsetime"].value == 250.0


def test_aws_count_metric_sums_all_periods():
    fake = _FakeCloudWatch()
    adapter = AwsMetricsAdapter(region="us-east-2", targets={"alb": "app/portal/abc"}, client=fake)
    result = adapter.collect(*WINDOW)
    sum_calls = [c for c in fake.calls if c["MetricName"] == "HTTPCode_Target_5XX_Count"]
    assert sum_calls and "Statistics" in sum_calls[0] and "ExtendedStatistics" not in sum_calls[0]
    # 5xx count sums across both periods (3 + 4), not just the latest datapoint.
    assert result.metrics["alb.httpcode_target_5xx_count"].value == 7.0


def test_aws_adapter_reports_rds_connection_peak_and_churn_proxy():
    fake = _FakeCloudWatch()
    adapter = AwsMetricsAdapter(region="us-east-2", targets={"rds_instance": "portal-db"}, client=fake)
    result = adapter.collect(*WINDOW)
    assert result.metrics["rds_instance.databaseconnections"].value == 15.0
    assert result.metrics["rds_instance.databaseconnections_peak"].value == 25.0
    churn = result.metrics["rds_instance.connection_churn_proxy"]
    assert churn.is_proxy is True
    assert churn.unit == "conn/s"
    assert churn.value == (20.0 - 10.0) / 300.0
    assert "lower-bound" in churn.provenance


def test_connection_churn_proxy_sorts_samples_and_uses_elapsed_seconds():
    points = [
        {"Timestamp": START + dt.timedelta(minutes=10), "Average": 12.0},
        {"Timestamp": START, "Average": 2.0},
        {"Timestamp": START + dt.timedelta(minutes=5), "Average": 8.0},
    ]
    assert _connection_churn_proxy(points) == (6.0 + 4.0) / 600.0


def test_connection_churn_proxy_needs_at_least_two_samples():
    assert _connection_churn_proxy([{"Timestamp": START, "Average": 2.0}]) is None


def test_aws_adapter_collects_request_count_per_target():
    # The portal scale-out signal: requests-per-target. AWS publishes it under the
    # LoadBalancer + TargetGroup dimension PAIR (Per AppELB, per TG), not TargetGroup
    # alone, so the query must carry both dimensions or it silently returns nothing.
    fake = _FakeCloudWatch()
    adapter = AwsMetricsAdapter(
        region="us-east-2",
        targets={"alb": "app/dev-portal/lb1", "target_group": "targetgroup/dev-portal/abc"},
        client=fake,
    )
    result = adapter.collect(*WINDOW)
    calls = [c for c in fake.calls if c["MetricName"] == "RequestCountPerTarget"]
    assert calls
    assert calls[0]["Dimensions"] == [
        {"Name": "LoadBalancer", "Value": "app/dev-portal/lb1"},
        {"Name": "TargetGroup", "Value": "targetgroup/dev-portal/abc"},
    ]
    assert calls[0]["Namespace"] == "AWS/ApplicationELB"
    # Summed across the window (3 + 4).
    assert result.metrics["target_group.requestcountpertarget"].value == 7.0


def test_request_count_per_target_needs_both_alb_and_target_group():
    # Only target_group configured (no LoadBalancer): named gap, no fabricated value.
    fake = _FakeCloudWatch()
    adapter = AwsMetricsAdapter(region="us-east-2", targets={"target_group": "targetgroup/dev-portal/abc"}, client=fake)
    result = adapter.collect(*WINDOW)
    assert "target_group.requestcountpertarget" not in result.metrics
    assert any("RequestCountPerTarget" in gap for gap in result.gaps)


def test_aws_adapter_collects_active_connection_count():
    fake = _FakeCloudWatch()
    adapter = AwsMetricsAdapter(region="us-east-2", targets={"alb": "app/portal/abc"}, client=fake)
    result = adapter.collect(*WINDOW)
    # Maximum across the window picks the busiest period (max(15, 25)).
    assert result.metrics["alb.activeconnectioncount"].value == 25.0


def test_aws_adapter_collects_portal_capacity_signals():
    # Custom Shifter/PortalCapacity gauges, dimensioned only by the low-cardinality
    # NamePrefix. Busy ratio reports both fleet mean (Average) and hottest worker
    # (Maximum); terminal sessions report the fleet total (Sum).
    fake = _FakeCloudWatch()
    adapter = AwsMetricsAdapter(region="us-east-2", targets={"name_prefix": "dev-portal"}, client=fake)
    result = adapter.collect(*WINDOW)
    cap_calls = [c for c in fake.calls if c["Namespace"] == "Shifter/PortalCapacity"]
    assert cap_calls
    assert all(c["Dimensions"] == [{"Name": "NamePrefix", "Value": "dev-portal"}] for c in cap_calls)
    assert result.metrics["name_prefix.workerbusyratio"].value == 15.0  # mean of per-period averages
    assert result.metrics["name_prefix.workerbusyratio_peak"].value == 25.0  # hottest worker
    # Count gauges sum across the window (3 + 4) so a fleet-total regression is caught.
    assert result.metrics["name_prefix.terminalactivesessions"].value == 7.0
    assert result.metrics["name_prefix.workerinflightrequests"].value == 7.0


def test_metric_value_can_be_flagged_as_proxy():
    mv = MetricValue(
        name="rds.connection_rate_proxy",
        value=12.5,
        unit="conn/sample",
        provenance="AWS/RDS DatabaseConnections (derivative)",
        is_proxy=True,
    )
    assert mv.is_proxy is True
    assert "derivative" in mv.provenance
