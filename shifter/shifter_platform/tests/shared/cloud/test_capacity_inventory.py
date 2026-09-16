"""Capacity-inventory adapters and factory (PLAT-201, #680).

The adapters are the only place raw provider quota/usage payloads exist. Their
contract is narrow and defensive: validate the response shape before any value
reaches policy, treat an absent datapoint as unmeasured rather than zero, never
raise into the pre-spinup path, and never log the payload.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings
from installation.contract import BackendCapability

from shared.capacity import (
    CapacityMetricSpec,
    CapacityReasonCode,
    MeasurementSource,
    PartitionRef,
    ProviderMetricRef,
)
from shared.cloud import get_capacity_inventory
from shared.cloud.aws.capacity_inventory import AWSCapacityInventory
from shared.cloud.exceptions import CloudProviderNotImplementedError

OBSERVED_AT = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
HOME_ACCOUNT = "111122223333"
OTHER_ACCOUNT = "123456789012"


def _partition(account: str = HOME_ACCOUNT) -> PartitionRef:
    return PartitionRef(
        name="aws-dev-use2",
        provider="aws",
        account=account,
        region="us-east-2",
        backend="ecs",
        policy_profile="default",
    )


def _spec(**overrides: object) -> CapacityMetricSpec:
    defaults: dict[str, object] = {
        "name": "ec2_vcpu",
        "dimension": "vcpu",
        "unit": "count",
        "partition": "aws-dev-use2",
        "source": MeasurementSource.PROVIDER_PROBE,
        "freshness_seconds": 900,
        "provider_ref": ProviderMetricRef(limit_ref="ec2/L-1216C47A", usage_ref="AWS/Usage/ResourceCount"),
    }
    defaults.update(overrides)
    return CapacityMetricSpec(**defaults)  # type: ignore[arg-type]


class FakeQuotasClient:
    """Stands in for the Service Quotas client."""

    def __init__(self, response=None, error: Exception | None = None):
        self._response = response if response is not None else {"Quota": {"Value": 512.0}}
        self._error = error
        self.calls: list[dict] = []

    def get_service_quota(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class FakeMetricsClient:
    """Stands in for the CloudWatch client."""

    def __init__(self, response=None, error: Exception | None = None):
        if response is None:
            response = {"MetricDataResults": [{"Values": [128.0], "Timestamps": [OBSERVED_AT]}]}
        self._response = response
        self._error = error
        self.calls: list[dict] = []

    def get_metric_data(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class FakeSTSClient:
    """Stands in for STS when a partition lives in another account."""

    def __init__(self):
        self.calls: list[dict] = []

    def assume_role(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "AKIAFAKE",
                "SecretAccessKey": "fake-secret",
                "SessionToken": "fake-token",
            }
        }


class RecordingFactory:
    """Client factory that hands out the fakes and records assume-role usage."""

    def __init__(self, quotas=None, metrics=None, sts=None):
        self.quotas = quotas or FakeQuotasClient()
        self.metrics = metrics or FakeMetricsClient()
        self.sts = sts or FakeSTSClient()
        self.requested: list[tuple[str, str, bool]] = []

    def __call__(self, service: str, *, region: str, credentials=None):
        self.requested.append((service, region, credentials is not None))
        return {"service-quotas": self.quotas, "cloudwatch": self.metrics, "sts": self.sts}[service]


def _inventory(factory: RecordingFactory) -> AWSCapacityInventory:
    return AWSCapacityInventory(client_factory=factory, home_account=HOME_ACCOUNT)


class TestFactoryCapabilityGate:
    """The factory fails closed when the backend does not declare the capability."""

    def test_capacity_inventory_is_a_declared_capability(self):
        assert BackendCapability.CAPACITY_INVENTORY.value == "capacity-inventory"

    @override_settings(CLOUD_PROVIDER="aws")
    def test_aws_returns_an_adapter(self):
        assert isinstance(get_capacity_inventory(), AWSCapacityInventory)

    @override_settings(CLOUD_PROVIDER="not-a-backend")
    def test_unknown_backend_fails_closed(self):
        with pytest.raises(CloudProviderNotImplementedError):
            get_capacity_inventory()


class TestObservationHappyPath:
    def test_reads_limit_and_usage_into_one_observation(self):
        factory = RecordingFactory()

        result = _inventory(factory).observe(_spec(), _partition())

        assert result.reason_code is None
        observation = result.observation
        assert observation is not None
        assert observation.limit == 512.0
        assert observation.usage == 128.0
        assert observation.observed_at == OBSERVED_AT
        assert observation.source is MeasurementSource.PROVIDER_PROBE

    def test_observed_at_comes_from_the_datapoint_not_wall_clock(self):
        """Freshness must reflect when the provider measured, not when we asked."""
        stamped = datetime(2026, 7, 26, 11, 30, tzinfo=UTC)
        metrics = FakeMetricsClient({"MetricDataResults": [{"Values": [4.0], "Timestamps": [stamped]}]})

        result = _inventory(RecordingFactory(metrics=metrics)).observe(_spec(), _partition())

        assert result.observation is not None
        assert result.observation.observed_at == stamped

    def test_quota_lookup_uses_the_spec_coordinates(self):
        factory = RecordingFactory()

        _inventory(factory).observe(_spec(), _partition())

        assert factory.quotas.calls[0]["ServiceCode"] == "ec2"
        assert factory.quotas.calls[0]["QuotaCode"] == "L-1216C47A"


class TestShapeValidation:
    """A malformed payload is unmeasured, never a fabricated number."""

    @pytest.mark.parametrize(
        "response",
        [
            {},
            {"Quota": {}},
            {"Quota": {"Value": None}},
            {"Quota": {"Value": "not-a-number"}},
        ],
    )
    def test_malformed_quota_response_is_unavailable(self, response):
        factory = RecordingFactory(quotas=FakeQuotasClient(response))

        result = _inventory(factory).observe(_spec(), _partition())

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    @pytest.mark.parametrize(
        "response",
        [
            {},
            {"MetricDataResults": []},
            {"MetricDataResults": [{"Values": [], "Timestamps": []}]},
            {"MetricDataResults": [{"Values": [1.0], "Timestamps": []}]},
            {"MetricDataResults": [{"Values": ["nope"], "Timestamps": [OBSERVED_AT]}]},
        ],
    )
    def test_malformed_or_empty_usage_response_is_unavailable(self, response):
        """No datapoint means we did not measure usage -- not that usage is zero."""
        factory = RecordingFactory(metrics=FakeMetricsClient(response))

        result = _inventory(factory).observe(_spec(), _partition())

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    def test_negative_quota_value_is_rejected(self):
        factory = RecordingFactory(quotas=FakeQuotasClient({"Quota": {"Value": -1.0}}))

        result = _inventory(factory).observe(_spec(), _partition())

        assert result.observation is None


class TestFailureHandling:
    """Provider failure degrades to indeterminate; it never raises into spinup."""

    def test_quota_client_error_is_swallowed(self):
        factory = RecordingFactory(quotas=FakeQuotasClient(error=RuntimeError("throttled")))

        result = _inventory(factory).observe(_spec(), _partition())

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    def test_metrics_client_error_is_swallowed(self):
        factory = RecordingFactory(metrics=FakeMetricsClient(error=RuntimeError("timeout")))

        result = _inventory(factory).observe(_spec(), _partition())

        assert result.observation is None

    def test_metric_without_provider_coordinates_is_unsupported(self):
        """A catalog entry with no adapter mapping is unsupported, not sufficient."""
        result = _inventory(RecordingFactory()).observe(_spec(provider_ref=None), _partition())

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.METRIC_UNSUPPORTED

    def test_failure_payload_is_not_logged(self, caplog):
        secret_ish = "arn:aws:iam::000000000000:role/super-secret"
        factory = RecordingFactory(quotas=FakeQuotasClient(error=RuntimeError(secret_ish)))

        with caplog.at_level("DEBUG"):
            _inventory(factory).observe(_spec(), _partition())

        assert secret_ish not in caplog.text
        assert "000000000000" not in caplog.text


class TestCrossAccountReads:
    """Cross-account partitions read through a constrained assumed role."""

    def test_same_account_does_not_assume_a_role(self):
        factory = RecordingFactory()

        _inventory(factory).observe(_spec(), _partition(HOME_ACCOUNT))

        assert factory.sts.calls == []
        assert all(used_credentials is False for _, _, used_credentials in factory.requested)

    @override_settings(CAPACITY_INVENTORY_ROLE_NAME="shifter-capacity-read")
    def test_other_account_assumes_the_configured_read_role(self):
        factory = RecordingFactory()

        result = _inventory(factory).observe(_spec(), _partition(OTHER_ACCOUNT))

        assert result.observation is not None
        assert factory.sts.calls[0]["RoleArn"] == f"arn:aws:iam::{OTHER_ACCOUNT}:role/shifter-capacity-read"
        # Quota and metric clients are built from the assumed credentials.
        assert ("service-quotas", "us-east-2", True) in factory.requested
        assert ("cloudwatch", "us-east-2", True) in factory.requested

    def test_assume_role_failure_is_indeterminate_not_a_crash(self):
        class FailingSTS(FakeSTSClient):
            def assume_role(self, **kwargs):
                raise RuntimeError("access denied")

        factory = RecordingFactory(sts=FailingSTS())

        result = _inventory(factory).observe(_spec(), _partition(OTHER_ACCOUNT))

        assert result.observation is None
        assert result.reason_code is CapacityReasonCode.MEASUREMENT_UNAVAILABLE

    def test_reads_target_the_partition_region(self):
        factory = RecordingFactory()
        partition = PartitionRef(
            name="aws-dev-usw2",
            provider="aws",
            account=HOME_ACCOUNT,
            region="us-west-2",
            backend="ecs",
            policy_profile="default",
        )

        _inventory(factory).observe(_spec(), partition)

        assert all(region == "us-west-2" for _, region, _ in factory.requested)


class TestStalenessIsRealNotSynthetic:
    """The adapter reports the provider's timestamp so policy can judge freshness."""

    def test_old_datapoint_is_returned_and_left_for_policy_to_reject(self):
        stale_at = OBSERVED_AT - timedelta(hours=6)
        metrics = FakeMetricsClient({"MetricDataResults": [{"Values": [1.0], "Timestamps": [stale_at]}]})

        result = _inventory(RecordingFactory(metrics=metrics)).observe(_spec(), _partition())

        assert result.observation is not None
        assert result.observation.is_stale(now=OBSERVED_AT, freshness_seconds=900) is True


class TestDefaultClientFactory:
    """The real boto3 factory is thin, but its credential wiring must be right."""

    def test_builds_a_client_without_credentials(self, monkeypatch):
        from shared.cloud.aws import capacity_inventory as mod

        seen = {}

        class FakeBoto:
            @staticmethod
            def client(service, **kwargs):
                seen["service"] = service
                seen["kwargs"] = kwargs
                return "client"

        monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto)

        assert mod._default_client_factory("sts", region="us-east-2") == "client"
        assert seen["service"] == "sts"
        assert "aws_access_key_id" not in seen["kwargs"]
        assert seen["kwargs"]["region_name"] == "us-east-2"

    def test_assumed_credentials_are_passed_through(self, monkeypatch):
        from shared.cloud.aws import capacity_inventory as mod

        seen = {}

        class FakeBoto:
            @staticmethod
            def client(service, **kwargs):
                seen.update(kwargs)
                return "client"

        monkeypatch.setitem(__import__("sys").modules, "boto3", FakeBoto)

        mod._default_client_factory(
            "cloudwatch",
            region="us-west-2",
            credentials={
                "AccessKeyId": "AKIAFAKE",
                "SecretAccessKey": "fake-secret",
                "SessionToken": "fake-token",
            },
        )

        assert seen["aws_access_key_id"] == "AKIAFAKE"
        assert seen["aws_session_token"] == "fake-token"

    def test_client_config_bounds_timeouts(self):
        """Capacity reads sit on the pre-spinup path and must fail fast."""
        from shared.cloud.aws.capacity_inventory import _client_config

        config = _client_config()

        assert config.connect_timeout == 2
        assert config.read_timeout == 5


class TestCoordinateHelpers:
    def test_missing_provider_ref_yields_empty_coordinates(self):
        from shared.cloud.aws.capacity_inventory import _limit_coordinates, _usage_coordinates

        spec = _spec(provider_ref=None)

        assert _limit_coordinates(spec) == ("", "", "")
        assert _usage_coordinates(spec) == ("", "", "")

    def test_limit_ref_without_a_separator_is_incomplete(self):
        """A malformed catalog ref must not become a half-formed API call."""
        factory = RecordingFactory()
        spec = _spec(provider_ref=ProviderMetricRef(limit_ref="ec2", usage_ref="AWS/Usage/ResourceCount"))

        result = _inventory(factory).observe(spec, _partition())

        assert result.observation is None
        assert factory.quotas.calls == []
