"""Tests for the shared GCP range audit telemetry policy (issue #2535).

The installation package validates ``settings.range_telemetry`` with this type and the
provisioner parses ``GCP_RANGE_TELEMETRY_POLICY_JSON`` with the same type. These tests pin
the default-on posture, the closed operator overrides, and the fail-closed runtime parse.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shared.gcp_range_telemetry import (
    FlowLogAggregationInterval,
    FlowLogMetadata,
    GcpRangeTelemetryPolicy,
    GcpRangeTelemetryPolicyError,
    NatLogFilter,
    dump_policy_json,
    load_policy_json,
)


def test_defaults_enable_every_control_with_documented_settings() -> None:
    policy = GcpRangeTelemetryPolicy()

    assert policy.vpc_flow_logs.enabled is True
    assert policy.vpc_flow_logs.aggregation_interval is FlowLogAggregationInterval.INTERVAL_5_SEC
    assert policy.vpc_flow_logs.flow_sampling == 0.5
    assert policy.vpc_flow_logs.metadata is FlowLogMetadata.INCLUDE_ALL_METADATA
    assert policy.nat_logs.enabled is True
    assert policy.nat_logs.filter is NatLogFilter.ALL
    assert policy.vertex_data_access_logs.enabled is True


def test_explicit_overrides_round_trip_through_json() -> None:
    policy = GcpRangeTelemetryPolicy.model_validate(
        {
            "vpc_flow_logs": {
                "enabled": True,
                "aggregation_interval": "INTERVAL_1_MIN",
                "flow_sampling": 0.1,
                "metadata": "EXCLUDE_ALL_METADATA",
            },
            "nat_logs": {"enabled": True, "filter": "ERRORS_ONLY"},
            "vertex_data_access_logs": {"enabled": False},
        }
    )

    assert load_policy_json(dump_policy_json(policy)) == policy
    assert json.loads(dump_policy_json(policy))["nat_logs"] == {"enabled": True, "filter": "ERRORS_ONLY"}


def test_partial_block_keeps_defaults_for_omitted_controls() -> None:
    policy = GcpRangeTelemetryPolicy.model_validate({"nat_logs": {"enabled": False}})

    assert policy.nat_logs.enabled is False
    assert policy.vpc_flow_logs == GcpRangeTelemetryPolicy().vpc_flow_logs
    assert policy.vertex_data_access_logs.enabled is True


def test_integer_one_is_full_sampling() -> None:
    policy = GcpRangeTelemetryPolicy.model_validate({"vpc_flow_logs": {"flow_sampling": 1}})

    assert policy.vpc_flow_logs.flow_sampling == 1.0
    assert isinstance(policy.vpc_flow_logs.flow_sampling, float)


@pytest.mark.parametrize(
    "payload",
    [
        {"vpc_flow_logs": {"enabled": "false"}},
        {"vpc_flow_logs": {"enabled": 0}},
        {"vpc_flow_logs": {"flow_sampling": 0}},
        {"vpc_flow_logs": {"flow_sampling": 1.5}},
        {"vpc_flow_logs": {"flow_sampling": True}},
        {"vpc_flow_logs": {"flow_sampling": "0.5"}},
        {"vpc_flow_logs": {"aggregation_interval": "INTERVAL_2_SEC"}},
        {"vpc_flow_logs": {"metadata": "CUSTOM_METADATA"}},
        {"nat_logs": {"filter": "SOME"}},
        {"nat_logs": {"enabled": "yes"}},
        {"vertex_data_access_logs": {"enabled": None}},
        {"vertex_data_access_logs": {"enabled": True, "exempted_members": ["user:x@example.com"]}},
        {"unknown_control": {}},
    ],
)
def test_invalid_or_unknown_values_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GcpRangeTelemetryPolicy.model_validate(payload)


def test_runtime_parse_defaults_only_when_unset() -> None:
    assert load_policy_json(None) == GcpRangeTelemetryPolicy()


@pytest.mark.parametrize("raw", ["", "   ", "not-json", "[]", '{"nat_logs": {"enabled": "off"}}'])
def test_runtime_parse_fails_closed_on_blank_or_malformed_values(raw: str) -> None:
    with pytest.raises(GcpRangeTelemetryPolicyError):
        load_policy_json(raw)


def test_runtime_parse_error_does_not_echo_the_rejected_value() -> None:
    with pytest.raises(GcpRangeTelemetryPolicyError) as excinfo:
        load_policy_json('{"nat_logs": {"filter": "secret-looking-token"}}')

    assert "secret-looking-token" not in str(excinfo.value)
