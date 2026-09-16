"""Tests for the shared Mission Control lease policy type (issue #27).

The policy is a single Django-free Pydantic contract shared by the installation
package (install-time validation) and Django settings (runtime binding). These
tests pin the backward-compatible defaults, the fail-fast validation rules, and
the JSON round-trip used to deliver the policy through ``MISSION_CONTROL_LEASE_POLICY_JSON``.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shared.mission_control_lease import (
    DEFAULT_EXTENSION_DAYS,
    DEFAULT_INITIAL_DAYS,
    DEFAULT_MAXIMUM_DAYS,
    MAX_LEASE_DAYS,
    MissionControlLeasePolicy,
    MissionControlLeasePolicyError,
    dump_policy_json,
    load_policy_json,
)


def _json(**fields: object) -> str:
    return json.dumps(fields)


def test_defaults_are_backward_compatible() -> None:
    policy = MissionControlLeasePolicy()
    assert (policy.initial_days, policy.extension_days, policy.maximum_days) == (30, 30, 365)
    assert policy.extensions_enabled is True
    assert (DEFAULT_INITIAL_DAYS, DEFAULT_EXTENSION_DAYS, DEFAULT_MAXIMUM_DAYS) == (30, 30, 365)


def test_custom_values_round_trip_through_json() -> None:
    policy = MissionControlLeasePolicy(initial_days=7, extension_days=3, maximum_days=90, extensions_enabled=False)
    assert load_policy_json(dump_policy_json(policy)) == policy


def test_absent_json_yields_defaults() -> None:
    # Only true absence (unset variable, passed as None) selects the defaults.
    assert load_policy_json(None) == MissionControlLeasePolicy()


@pytest.mark.parametrize("raw", ["", "   ", "\n\t"])
def test_present_but_blank_json_is_rejected(raw: str) -> None:
    # A present but blank value is a broken substitution, not an omission (ADR-011-R9).
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(raw)


def test_initial_may_not_exceed_maximum() -> None:
    payload = _json(initial_days=100, maximum_days=30)
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


def test_initial_equal_to_maximum_is_valid() -> None:
    policy = load_policy_json(_json(initial_days=30, maximum_days=30))
    assert policy.initial_days == policy.maximum_days == 30


def test_extension_greater_than_maximum_is_valid() -> None:
    # An extension is bounded by remaining lifetime, so increment > maximum is allowed.
    policy = load_policy_json(_json(initial_days=10, extension_days=1000, maximum_days=30))
    assert policy.extension_days == 1000


@pytest.mark.parametrize("field", ["initial_days", "extension_days", "maximum_days"])
@pytest.mark.parametrize("value", [0, -1])
def test_nonpositive_durations_rejected(field: str, value: int) -> None:
    payload = _json(**{field: value})
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


@pytest.mark.parametrize("field", ["initial_days", "extension_days", "maximum_days"])
def test_duration_above_max_is_rejected(field: str) -> None:
    # Pair with maximum_days=MAX so an over-max initial/extension trips the field's own
    # upper bound, not the initial<=maximum cross-field rule (which would confound it).
    payload = _json(**{"maximum_days": MAX_LEASE_DAYS, field: MAX_LEASE_DAYS + 1})
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


@pytest.mark.parametrize("field", ["initial_days", "extension_days", "maximum_days"])
def test_max_boundary_is_accepted_and_preserved(field: str) -> None:
    policy = load_policy_json(_json(**{"maximum_days": MAX_LEASE_DAYS, field: MAX_LEASE_DAYS}))
    assert getattr(policy, field) == MAX_LEASE_DAYS


def test_unknown_fields_rejected() -> None:
    payload = _json(initial_days=30, bogus=1)
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


@pytest.mark.parametrize("field", ["initial_days", "extension_days", "maximum_days"])
def test_explicit_null_rejected(field: str) -> None:
    payload = _json(**{field: None})
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


@pytest.mark.parametrize("field", ["initial_days", "extension_days", "maximum_days"])
def test_boolean_in_integer_field_rejected(field: str) -> None:
    payload = _json(**{field: True})
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


@pytest.mark.parametrize("field", ["initial_days", "extension_days", "maximum_days"])
@pytest.mark.parametrize("value", ["30", 30.5])
def test_string_or_fractional_duration_rejected(field: str, value: object) -> None:
    payload = _json(**{field: value})
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


@pytest.mark.parametrize("value", [1, 0, "true"])
def test_non_boolean_switch_rejected(value: object) -> None:
    payload = _json(extensions_enabled=value)
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(payload)


def test_malformed_json_rejected() -> None:
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json("{not json")


@pytest.mark.parametrize("raw", ["[1, 2, 3]", "42", '"string"'])
def test_non_object_json_rejected(raw: str) -> None:
    with pytest.raises(MissionControlLeasePolicyError):
        load_policy_json(raw)


def test_model_validate_raises_pydantic_error_for_installer_boundary() -> None:
    # The installer consumes the raw ValidationError (like RangeEgressPolicy) to
    # build anchored ConfigIssues, so the model itself must surface it.
    with pytest.raises(ValidationError):
        MissionControlLeasePolicy.model_validate({"initial_days": 0})


def test_dump_is_compact_and_complete() -> None:
    policy = MissionControlLeasePolicy(initial_days=5, extension_days=2, maximum_days=50, extensions_enabled=False)
    dumped = dump_policy_json(policy)
    assert json.loads(dumped) == {
        "initial_days": 5,
        "extension_days": 2,
        "maximum_days": 50,
        "extensions_enabled": False,
    }
    assert " " not in dumped
