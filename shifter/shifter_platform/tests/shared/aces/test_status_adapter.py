"""Tests for the runtime-safe ACES operation-status -> ResourceStatus adapter (#1274)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from shared.aces.status import (
    ACES_OPERATION_STATES,
    MAX_DIAGNOSTIC_TEXT_LEN,
    AcesStatusProjection,
    ProjectionDecision,
    RangeOperation,
    project_operation_status,
)
from shared.enums import ResourceStatus

TS = datetime(2026, 7, 5, 3, 0, tzinfo=UTC)

# The explicit, authoritative (intent, state) -> ResourceStatus expectations.
EXPECTED_MAP = {
    (RangeOperation.PROVISION, "accepted"): ResourceStatus.PENDING,
    (RangeOperation.PROVISION, "running"): ResourceStatus.PROVISIONING,
    (RangeOperation.PROVISION, "succeeded"): ResourceStatus.READY,
    (RangeOperation.PROVISION, "failed"): ResourceStatus.FAILED,
    (RangeOperation.PROVISION, "cancelled"): ResourceStatus.FAILED,
    (RangeOperation.DESTROY, "accepted"): ResourceStatus.DESTROYING,
    (RangeOperation.DESTROY, "running"): ResourceStatus.DESTROYING,
    (RangeOperation.DESTROY, "succeeded"): ResourceStatus.DESTROYED,
    (RangeOperation.DESTROY, "failed"): ResourceStatus.FAILED,
    (RangeOperation.DESTROY, "cancelled"): ResourceStatus.FAILED,
    (RangeOperation.PAUSE, "accepted"): ResourceStatus.PAUSING,
    (RangeOperation.PAUSE, "running"): ResourceStatus.PAUSING,
    (RangeOperation.PAUSE, "succeeded"): ResourceStatus.PAUSED,
    (RangeOperation.PAUSE, "failed"): ResourceStatus.FAILED,
    (RangeOperation.PAUSE, "cancelled"): ResourceStatus.FAILED,
    (RangeOperation.RESUME, "accepted"): ResourceStatus.RESUMING,
    (RangeOperation.RESUME, "running"): ResourceStatus.RESUMING,
    (RangeOperation.RESUME, "succeeded"): ResourceStatus.READY,
    (RangeOperation.RESUME, "failed"): ResourceStatus.FAILED,
    (RangeOperation.RESUME, "cancelled"): ResourceStatus.FAILED,
}


@pytest.mark.parametrize(("intent", "state"), list(EXPECTED_MAP.keys()))
def test_every_intent_state_maps_to_expected_status(intent, state):
    result = project_operation_status(operation_state=state, intent=intent, source_timestamp=TS)
    assert result.decision is ProjectionDecision.APPLY
    assert result.target_status is EXPECTED_MAP[(intent, state)]


def test_mapping_covers_every_intent_and_state_combination():
    # Guard against a state or intent being added without a mapping vector.
    assert set(EXPECTED_MAP.keys()) == {(intent, state) for intent in RangeOperation for state in ACES_OPERATION_STATES}


@pytest.mark.parametrize("state", ["queued", "SUCCEEDED", "", "unknown", "provisioning"])
def test_unknown_state_is_unmappable(state):
    result = project_operation_status(operation_state=state, intent=RangeOperation.PROVISION, source_timestamp=TS)
    assert result.decision is ProjectionDecision.UNMAPPABLE
    assert result.target_status is None


@pytest.mark.parametrize("intent", ["reboot", "", "RANGE", "ngfw"])
def test_unknown_intent_is_unmappable(intent):
    result = project_operation_status(operation_state="running", intent=intent, source_timestamp=TS)
    assert result.decision is ProjectionDecision.UNMAPPABLE
    assert result.target_status is None


def test_string_intent_is_accepted():
    result = project_operation_status(operation_state="succeeded", intent="provision", source_timestamp=TS)
    assert result.decision is ProjectionDecision.APPLY
    assert result.target_status is ResourceStatus.READY


def test_older_observation_is_stale():
    result = project_operation_status(
        operation_state="succeeded",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS - timedelta(seconds=1),
        previous_source_timestamp=TS,
    )
    assert result.decision is ProjectionDecision.STALE
    assert result.target_status is None


def test_equal_observation_is_duplicate():
    result = project_operation_status(
        operation_state="succeeded",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS,
        previous_source_timestamp=TS,
    )
    assert result.decision is ProjectionDecision.DUPLICATE
    assert result.target_status is None


def test_newer_observation_applies_over_previous():
    result = project_operation_status(
        operation_state="succeeded",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS + timedelta(seconds=1),
        previous_source_timestamp=TS,
    )
    assert result.decision is ProjectionDecision.APPLY
    assert result.target_status is ResourceStatus.READY


def test_unknown_state_wins_over_staleness_check():
    # An unknown state is rejected regardless of timing.
    result = project_operation_status(
        operation_state="bogus",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS - timedelta(days=1),
        previous_source_timestamp=TS,
    )
    assert result.decision is ProjectionDecision.UNMAPPABLE


def test_diagnostic_ref_is_sanitized_to_allowed_keys():
    result = project_operation_status(
        operation_state="failed",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS,
        status_reason="terraform apply failed",
        diagnostic_refs={
            "error_class": "TerraformError",
            "log_ref": "logs/op-123",
            # Disallowed keys must be dropped, never surfaced.
            "aws_secret_access_key": "AKIAEXAMPLE",
            "raw_output": "provider dump ...",
        },
    )
    assert result.decision is ProjectionDecision.APPLY
    assert result.diagnostic_ref == {
        "error_class": "TerraformError",
        "log_ref": "logs/op-123",
        "status_reason": "terraform apply failed",
    }


def test_error_message_is_bounded_and_single_line():
    reason = "line one\nline two\t" + "x" * 400
    result = project_operation_status(
        operation_state="failed",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS,
        status_reason=reason,
    )
    assert result.error_message is not None
    assert "\n" not in result.error_message
    assert "\t" not in result.error_message
    assert len(result.error_message) <= MAX_DIAGNOSTIC_TEXT_LEN
    assert len(result.diagnostic_ref["status_reason"]) <= MAX_DIAGNOSTIC_TEXT_LEN


def test_diagnostic_ref_values_are_bounded():
    result = project_operation_status(
        operation_state="failed",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS,
        diagnostic_refs={"error_class": "E" * 500},
    )
    assert len(result.diagnostic_ref["error_class"]) <= MAX_DIAGNOSTIC_TEXT_LEN


def test_no_error_message_without_status_reason():
    result = project_operation_status(
        operation_state="failed",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS,
    )
    assert result.error_message is None


def test_no_diagnostic_ref_when_empty():
    result = project_operation_status(
        operation_state="running",
        intent=RangeOperation.PROVISION,
        source_timestamp=TS,
    )
    assert result.diagnostic_ref is None


def test_projection_is_frozen():
    result = project_operation_status(operation_state="running", intent=RangeOperation.PROVISION, source_timestamp=TS)
    assert isinstance(result, AcesStatusProjection)
    with pytest.raises(FrozenInstanceError):
        result.decision = ProjectionDecision.STALE  # type: ignore[misc]


def test_runtime_states_match_aces_sdl_enum():
    """Drift guard: the runtime-safe state set must match the ACES SDL enum.

    The SDL is a dev/test dependency only; the runtime adapter never imports it.
    """
    runtime_state = pytest.importorskip("aces_contracts.runtime_state")
    sdl_states = {member.value for member in runtime_state.OperationState}
    assert sdl_states == ACES_OPERATION_STATES
