"""Tests for the closed operation-result contract (ADR-043 phase 4, #1836)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from shared.operation_envelope import canonical_payload_digest
from shared.operation_results import (
    OperationResultError,
    ResultStep,
    build_result_identity,
    has_contract,
    is_terminal_step,
    latest_step,
    parse_result_payload,
    step_follows,
    steps_for,
)

RANGE_PAUSE = ("range", "pause")
RANGE_RESUME = ("range", "resume")

INSTANCE_UUID = "6c3f6f3e-6b2b-4f5e-9a1e-2b7c1d4e5f60"
OTHER_UUID = "7d4a7a4f-7c3c-4a6f-8b2f-3c8d2e5f6a71"


def _instance_outcome(uuid: str = INSTANCE_UUID, status: str = "paused") -> dict[str, object]:
    return {"instance_uuid": uuid, "status": status}


class TestStepVocabularyIsClosed:
    """Step keys are a closed enumeration scoped to a (resource, operation)."""

    def test_steps_for_returns_the_declared_family(self):
        assert ResultStep.RANGE_INSTANCES_PAUSED in steps_for(*RANGE_PAUSE)
        assert ResultStep.RANGE_TERMINAL_PAUSED in steps_for(*RANGE_PAUSE)

    def test_unknown_resource_operation_pair_is_rejected(self):
        with pytest.raises(OperationResultError):
            steps_for("range", "provision")

    def test_step_from_another_operation_is_rejected(self):
        # A resume step must not be accepted under a pause operation.
        payload = {"instances": [_instance_outcome(status="ready")]}
        with pytest.raises(OperationResultError):
            parse_result_payload(*RANGE_PAUSE, step=ResultStep.RANGE_INSTANCES_READY, payload=payload)


class TestPayloadParserIsClosed:
    """Payloads are parsed by a closed contract, never passed through."""

    def test_valid_range_pause_payload_round_trips(self):
        parsed = parse_result_payload(
            *RANGE_PAUSE,
            step=ResultStep.RANGE_INSTANCES_PAUSED,
            payload={"instances": [_instance_outcome()]},
        )
        assert parsed["instances"][0]["instance_uuid"] == INSTANCE_UUID

    def test_unknown_key_is_rejected(self):
        payload = {"instances": [_instance_outcome()], "state": {"arbitrary": "merge"}}
        with pytest.raises(OperationResultError):
            parse_result_payload(*RANGE_PAUSE, step=ResultStep.RANGE_INSTANCES_PAUSED, payload=payload)

    def test_engine_integer_primary_key_is_not_accepted_as_identity(self):
        with pytest.raises(OperationResultError):
            parse_result_payload(
                *RANGE_PAUSE,
                step=ResultStep.RANGE_INSTANCES_PAUSED,
                payload={"instances": [{"instance_id": 41, "status": "paused"}]},
            )

    def test_instance_uuid_must_be_a_uuid(self):
        payload = {"instances": [_instance_outcome(uuid="not-a-uuid")]}
        with pytest.raises(OperationResultError):
            parse_result_payload(*RANGE_PAUSE, step=ResultStep.RANGE_INSTANCES_PAUSED, payload=payload)

    def test_status_must_be_in_the_shared_vocabulary(self):
        payload = {"instances": [_instance_outcome(status="halted")]}
        with pytest.raises(OperationResultError):
            parse_result_payload(*RANGE_PAUSE, step=ResultStep.RANGE_INSTANCES_PAUSED, payload=payload)

    def test_status_must_match_the_step_it_reports(self):
        # The pause step reports paused instances; a ready instance is incoherent.
        payload = {"instances": [_instance_outcome(status="ready")]}
        with pytest.raises(OperationResultError):
            parse_result_payload(*RANGE_PAUSE, step=ResultStep.RANGE_INSTANCES_PAUSED, payload=payload)

    def test_instance_outcomes_are_bounded(self):
        payload = {"instances": [_instance_outcome(uuid=f"00000000-0000-4000-8000-{i:012d}") for i in range(257)]}
        with pytest.raises(OperationResultError):
            parse_result_payload(*RANGE_PAUSE, step=ResultStep.RANGE_INSTANCES_PAUSED, payload=payload)

    def test_failure_payload_requires_a_closed_reason_code(self):
        with pytest.raises(OperationResultError):
            parse_result_payload(
                *RANGE_PAUSE,
                step=ResultStep.RANGE_TERMINAL_FAILED,
                payload={"reason_code": "something_went_wrong", "diagnostic": "boom"},
            )

    def test_failure_payload_accepts_a_closed_reason_code(self):
        parsed = parse_result_payload(
            *RANGE_PAUSE,
            step=ResultStep.RANGE_TERMINAL_FAILED,
            payload={"reason_code": "cloud_operation_failed", "diagnostic": "stop timed out"},
        )
        assert parsed["reason_code"] == "cloud_operation_failed"

    def test_failure_diagnostic_is_bounded(self):
        with pytest.raises(OperationResultError):
            parse_result_payload(
                *RANGE_PAUSE,
                step=ResultStep.RANGE_TERMINAL_FAILED,
                payload={"reason_code": "cloud_operation_failed", "diagnostic": "x" * 1024},
            )

    def test_ngfw_cascade_payload_carries_the_ngfw_instance_uuid(self):
        parsed = parse_result_payload(
            *RANGE_PAUSE,
            step=ResultStep.RANGE_NGFW_CASCADE_PAUSED,
            payload={"ngfw_instance_uuid": INSTANCE_UUID, "status": "paused"},
        )
        assert parsed["ngfw_instance_uuid"] == INSTANCE_UUID


class TestStepIdentityIsDeterministic:
    """The same semantic step on retry reproduces the same identity."""

    def test_identity_is_stable_across_retries(self):
        payload = {"instances": [_instance_outcome()]}
        digest = canonical_payload_digest(payload)
        first = build_result_identity(operation_id=OTHER_UUID, step=ResultStep.RANGE_INSTANCES_PAUSED, digest=digest)
        second = build_result_identity(operation_id=OTHER_UUID, step=ResultStep.RANGE_INSTANCES_PAUSED, digest=digest)
        assert first == second

    def test_identity_is_insensitive_to_payload_key_order(self):
        a = canonical_payload_digest({"ngfw_instance_uuid": INSTANCE_UUID, "status": "paused"})
        b = canonical_payload_digest({"status": "paused", "ngfw_instance_uuid": INSTANCE_UUID})
        assert a == b

    def test_distinct_steps_of_one_operation_do_not_collide(self):
        digest = canonical_payload_digest({"instances": [_instance_outcome()]})
        paused = build_result_identity(operation_id=OTHER_UUID, step=ResultStep.RANGE_INSTANCES_PAUSED, digest=digest)
        terminal = build_result_identity(operation_id=OTHER_UUID, step=ResultStep.RANGE_TERMINAL_PAUSED, digest=digest)
        assert paused != terminal

    def test_conflicting_payload_for_one_step_yields_a_distinct_identity(self):
        # A conflicting replay must not silently collapse onto the harmless-replay
        # identity: the applier detects two digests for one step as a conflict.
        one = canonical_payload_digest({"instances": [_instance_outcome()]})
        two = canonical_payload_digest({"instances": [_instance_outcome(uuid=OTHER_UUID)]})
        assert build_result_identity(
            operation_id=OTHER_UUID, step=ResultStep.RANGE_INSTANCES_PAUSED, digest=one
        ) != build_result_identity(operation_id=OTHER_UUID, step=ResultStep.RANGE_INSTANCES_PAUSED, digest=two)

    def test_identity_embeds_the_operation_generation(self):
        digest = canonical_payload_digest({"instances": [_instance_outcome()]})
        assert OTHER_UUID in build_result_identity(
            operation_id=OTHER_UUID, step=ResultStep.RANGE_INSTANCES_PAUSED, digest=digest
        )


class TestLatestStep:
    """The applier judges ordering against the high-water mark, not the last row."""

    def test_empty_history_has_no_latest_step(self):
        assert latest_step(*RANGE_PAUSE, []) is None

    def test_returns_the_furthest_advanced_step(self):
        applied = [ResultStep.RANGE_NGFW_CASCADE_PAUSING, ResultStep.RANGE_INSTANCES_PAUSED]
        assert latest_step(*RANGE_PAUSE, applied) == ResultStep.RANGE_NGFW_CASCADE_PAUSING

    def test_order_of_the_input_does_not_matter(self):
        forwards = [ResultStep.RANGE_INSTANCES_PAUSED, ResultStep.RANGE_TERMINAL_PAUSED]
        assert latest_step(*RANGE_PAUSE, forwards) == latest_step(*RANGE_PAUSE, list(reversed(forwards)))

    def test_a_terminal_step_outranks_a_same_rank_progress_step(self):
        # Terminal and failure share a rank; an applied terminal must win so a
        # later progress result is judged against it.
        applied = [ResultStep.RANGE_TERMINAL_PAUSED, ResultStep.RANGE_NGFW_CASCADE_PAUSED]
        assert is_terminal_step(*RANGE_PAUSE, step=latest_step(*RANGE_PAUSE, applied))

    def test_high_water_mark_blocks_a_late_progress_result(self):
        applied = [ResultStep.RANGE_INSTANCES_PAUSED, ResultStep.RANGE_TERMINAL_PAUSED]
        previous = latest_step(*RANGE_PAUSE, applied)
        assert not step_follows(*RANGE_PAUSE, previous=previous, step=ResultStep.RANGE_NGFW_CASCADE_PAUSED)


class TestStepOrderAndTerminality:
    """Ordering is closed per (resource, operation); terminal state never regresses."""

    def test_first_step_of_an_operation_is_legal(self):
        assert step_follows(*RANGE_PAUSE, previous=None, step=ResultStep.RANGE_INSTANCES_PAUSED)

    def test_forward_progress_is_legal(self):
        assert step_follows(
            *RANGE_PAUSE,
            previous=ResultStep.RANGE_INSTANCES_PAUSED,
            step=ResultStep.RANGE_TERMINAL_PAUSED,
        )

    def test_backward_progress_is_rejected(self):
        assert not step_follows(
            *RANGE_PAUSE,
            previous=ResultStep.RANGE_TERMINAL_PAUSED,
            step=ResultStep.RANGE_INSTANCES_PAUSED,
        )

    def test_repeat_of_the_same_step_is_legal(self):
        # Same-rank replay is harmless; the digest decides replay vs conflict.
        assert step_follows(
            *RANGE_PAUSE,
            previous=ResultStep.RANGE_INSTANCES_PAUSED,
            step=ResultStep.RANGE_INSTANCES_PAUSED,
        )

    def test_progress_after_a_terminal_step_is_rejected(self):
        assert not step_follows(
            *RANGE_PAUSE,
            previous=ResultStep.RANGE_TERMINAL_PAUSED,
            step=ResultStep.RANGE_NGFW_CASCADE_PAUSED,
        )

    def test_failure_after_a_terminal_success_is_rejected(self):
        assert not step_follows(
            *RANGE_PAUSE,
            previous=ResultStep.RANGE_TERMINAL_PAUSED,
            step=ResultStep.RANGE_TERMINAL_FAILED,
        )

    def test_terminal_steps_are_reported_terminal(self):
        assert is_terminal_step(*RANGE_PAUSE, step=ResultStep.RANGE_TERMINAL_PAUSED)
        assert is_terminal_step(*RANGE_PAUSE, step=ResultStep.RANGE_TERMINAL_FAILED)

    def test_progress_steps_are_not_terminal(self):
        assert not is_terminal_step(*RANGE_PAUSE, step=ResultStep.RANGE_INSTANCES_PAUSED)

    def test_resume_cascade_precedes_instance_readiness(self):
        # ensure_ngfw_running runs before instances start on resume.
        assert step_follows(
            *RANGE_RESUME,
            previous=ResultStep.RANGE_NGFW_CASCADE_READY,
            step=ResultStep.RANGE_INSTANCES_READY,
        )
        assert not step_follows(
            *RANGE_RESUME,
            previous=ResultStep.RANGE_INSTANCES_READY,
            step=ResultStep.RANGE_NGFW_CASCADE_READY,
        )

    def test_one_operation_emits_several_distinct_observations(self):
        # The whole reason a step key exists: one pause emits instance, cascade,
        # and terminal results, and the cascade reports two statuses. The step
        # key distinguishes and orders them; result_kind alone could not.
        observations = [
            ResultStep.RANGE_INSTANCES_PAUSED,
            ResultStep.RANGE_NGFW_CASCADE_PAUSING,
            ResultStep.RANGE_NGFW_CASCADE_PAUSED,
            ResultStep.RANGE_TERMINAL_PAUSED,
        ]
        assert len(set(observations)) == len(observations)
        for previous, step in pairwise(observations):
            assert step_follows(*RANGE_PAUSE, previous=previous, step=step)

    def test_step_not_declared_for_the_operation_is_rejected(self):
        with pytest.raises(OperationResultError):
            step_follows(*RANGE_RESUME, previous=None, step=ResultStep.RANGE_TERMINAL_PAUSED)

    def test_direct_ngfw_operations_are_declared(self):
        for operation in ("provision", "deprovision", "start", "stop"):
            assert has_contract("ngfw", operation) is True
        assert has_contract("range", "pause") is True

    def test_ngfw_provision_orders_its_repeated_provisioning_observations(self):
        # Three provision steps all report `provisioning`; only the step key
        # distinguishes and orders them.
        observations = [
            ResultStep.NGFW_PROVISION_REQUESTED,
            ResultStep.NGFW_PROVISION_INFRA,
            ResultStep.NGFW_PROVISION_READY,
        ]
        for previous, step in pairwise(observations):
            assert step_follows("ngfw", "provision", previous=previous, step=step)
        assert not step_follows(
            "ngfw", "provision", previous=ResultStep.NGFW_PROVISION_READY, step=ResultStep.NGFW_PROVISION_REQUESTED
        )

    def test_provision_ends_paused_because_the_ngfw_is_auto_stopped(self):
        assert is_terminal_step("ngfw", "provision", step=ResultStep.NGFW_PROVISION_AUTOSTOP)
        assert not is_terminal_step("ngfw", "provision", step=ResultStep.NGFW_PROVISION_READY)
