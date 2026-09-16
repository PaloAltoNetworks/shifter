"""RAES step tables in the closed operation-result contract (ADR-043 phase 5, #1837).

Drives the ``("raes-range", "provision")`` and ``("raes-range", "destroy")``
additions to ``shared.operation_results``: step declaration, payload shapes,
legal order, terminality, and retry-stable identity.

The pause/resume and NGFW families are covered by ``test_operation_results.py``;
this file stays focused on what phase 5 adds.
"""

from __future__ import annotations

import pytest

from shared.enums import ResourceStatus
from shared.operation_results import (
    MAX_DIAGNOSTIC_CHARS,
    MAX_SNAPSHOT_RESOURCES,
    OperationResultError,
    ResultStep,
    build_result_identity,
    has_contract,
    is_terminal_step,
    latest_step,
    parse_result_payload,
    range_status_for,
    result_kind_for,
    step_follows,
    steps_for,
)
from shared.raes.status import RAES_STATE_RUNNING, RAES_STATE_SUCCEEDED

_OPERATION_ID = "11111111-2222-3333-4444-555555555555"


def _snapshot_payload(count: int = 2) -> dict:
    return {
        "resources": [
            {"address": f"node.n{index}", "resource_type": "node", "status": "provisioned"} for index in range(count)
        ]
    }


class TestContractDeclaration:
    def test_both_raes_operations_have_a_contract(self):
        assert has_contract("raes-range", "provision") is True
        assert has_contract("raes-range", "destroy") is True

    def test_provision_declares_its_steps(self):
        assert steps_for("raes-range", "provision") == frozenset(
            {
                ResultStep.RAES_PROVISION_RUNNING,
                ResultStep.RAES_PROVISION_SNAPSHOT,
                ResultStep.RAES_TERMINAL_READY,
                ResultStep.RAES_TERMINAL_FAILED,
            }
        )

    def test_destroy_declares_its_steps(self):
        assert steps_for("raes-range", "destroy") == frozenset(
            {
                ResultStep.RAES_DESTROY_RUNNING,
                ResultStep.RAES_TERMINAL_DESTROYED,
                ResultStep.RAES_TERMINAL_FAILED,
            }
        )

    def test_pause_resume_still_share_the_range_tables(self):
        assert steps_for("raes-range", "pause") == steps_for("range", "pause")
        assert steps_for("raes-range", "resume") == steps_for("range", "resume")

    def test_result_kinds_match_the_step_role(self):
        assert result_kind_for("raes-range", "provision", step=ResultStep.RAES_PROVISION_RUNNING) == "RESOURCE_STATE"
        assert result_kind_for("raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT) == "RESOURCE_STATE"
        assert result_kind_for("raes-range", "provision", step=ResultStep.RAES_TERMINAL_READY) == "TERMINAL_SUCCESS"
        assert result_kind_for("raes-range", "destroy", step=ResultStep.RAES_TERMINAL_FAILED) == "TERMINAL_FAILURE"

    def test_only_terminal_steps_terminate(self):
        assert is_terminal_step("raes-range", "provision", step=ResultStep.RAES_TERMINAL_READY) is True
        assert is_terminal_step("raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT) is False
        assert is_terminal_step("raes-range", "destroy", step=ResultStep.RAES_TERMINAL_DESTROYED) is True

    def test_a_step_from_the_other_operation_is_refused(self):
        # A destroy step must not be accepted under a provision generation.
        with pytest.raises(OperationResultError):
            result_kind_for("raes-range", "provision", step=ResultStep.RAES_TERMINAL_DESTROYED)


class TestRangeStatusProjection:
    """Which steps move ``Range.status``, and to what."""

    def test_provision_running_projects_provisioning(self):
        assert range_status_for("raes-range", "provision", step=ResultStep.RAES_PROVISION_RUNNING) == (
            ResourceStatus.PROVISIONING.value
        )

    def test_terminal_success_projects_the_lifecycle_status(self):
        assert range_status_for("raes-range", "provision", step=ResultStep.RAES_TERMINAL_READY) == (
            ResourceStatus.READY.value
        )
        assert range_status_for("raes-range", "destroy", step=ResultStep.RAES_TERMINAL_DESTROYED) == (
            ResourceStatus.DESTROYED.value
        )

    def test_snapshot_projects_no_status(self):
        # A snapshot is bounded evidence: it must never move lifecycle state.
        assert range_status_for("raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT) is None

    def test_destroy_running_projects_no_status(self):
        # The pre-cutover destroy path published no "destroying" range event; the
        # observation is sidecar evidence only. Projecting one here would be a
        # new lifecycle write, not a port of existing behaviour.
        assert range_status_for("raes-range", "destroy", step=ResultStep.RAES_DESTROY_RUNNING) is None


class TestOperationPayload:
    def test_running_payload_round_trips(self):
        parsed = parse_result_payload(
            "raes-range",
            "provision",
            step=ResultStep.RAES_PROVISION_RUNNING,
            payload={"raes_status": RAES_STATE_RUNNING},
        )
        assert parsed == {"raes_status": RAES_STATE_RUNNING}

    def test_status_reason_is_optional_and_bounded(self):
        parsed = parse_result_payload(
            "raes-range",
            "provision",
            step=ResultStep.RAES_PROVISION_RUNNING,
            payload={"raes_status": RAES_STATE_RUNNING, "status_reason": "waiting on composition"},
        )
        assert parsed["status_reason"] == "waiting on composition"

        with pytest.raises(OperationResultError):
            parse_result_payload(
                "raes-range",
                "provision",
                step=ResultStep.RAES_PROVISION_RUNNING,
                payload={"raes_status": RAES_STATE_RUNNING, "status_reason": "x" * (MAX_DIAGNOSTIC_CHARS + 1)},
            )

    def test_raes_status_is_pinned_to_the_step(self):
        # A "succeeded" body under the running step would let a late progress
        # result masquerade as completion.
        with pytest.raises(OperationResultError):
            parse_result_payload(
                "raes-range",
                "provision",
                step=ResultStep.RAES_PROVISION_RUNNING,
                payload={"raes_status": RAES_STATE_SUCCEEDED},
            )

    def test_unknown_raes_state_is_refused(self):
        with pytest.raises(OperationResultError):
            parse_result_payload(
                "raes-range",
                "provision",
                step=ResultStep.RAES_TERMINAL_READY,
                payload={"raes_status": "totally-done"},
            )

    def test_unexpected_field_is_refused(self):
        with pytest.raises(OperationResultError):
            parse_result_payload(
                "raes-range",
                "provision",
                step=ResultStep.RAES_PROVISION_RUNNING,
                payload={"raes_status": RAES_STATE_RUNNING, "range_config": {}},
            )


class TestSnapshotPayload:
    def test_snapshot_round_trips(self):
        parsed = parse_result_payload(
            "raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT, payload=_snapshot_payload()
        )
        assert [entry["address"] for entry in parsed["resources"]] == ["node.n0", "node.n1"]

    def test_snapshot_is_bounded(self):
        oversized = _snapshot_payload(MAX_SNAPSHOT_RESOURCES + 1)
        with pytest.raises(OperationResultError):
            parse_result_payload("raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT, payload=oversized)

    def test_snapshot_entry_is_closed_on_keys(self):
        payload = _snapshot_payload(1)
        payload["resources"][0]["public_ip"] = "203.0.113.7"
        with pytest.raises(OperationResultError):
            parse_result_payload("raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT, payload=payload)

    def test_empty_snapshot_is_allowed(self):
        # A plan with no realized resources is legal; an empty list is not an error.
        parsed = parse_result_payload(
            "raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT, payload={"resources": []}
        )
        assert parsed == {"resources": []}


class TestFailurePayload:
    def test_failure_carries_an_authored_reason_code(self):
        parsed = parse_result_payload(
            "raes-range",
            "provision",
            step=ResultStep.RAES_TERMINAL_FAILED,
            payload={"reason_code": "cloud_operation_failed", "diagnostic": "composition verification incomplete"},
        )
        assert parsed["reason_code"] == "cloud_operation_failed"

    def test_unauthored_reason_code_is_refused(self):
        with pytest.raises(OperationResultError):
            parse_result_payload(
                "raes-range",
                "destroy",
                step=ResultStep.RAES_TERMINAL_FAILED,
                payload={"reason_code": "KeyError: 'range_id'", "diagnostic": ""},
            )


class TestOrdering:
    def test_provision_order_is_legal_forwards(self):
        assert step_follows("raes-range", "provision", previous=None, step=ResultStep.RAES_PROVISION_RUNNING)
        assert step_follows(
            "raes-range",
            "provision",
            previous=ResultStep.RAES_PROVISION_RUNNING,
            step=ResultStep.RAES_PROVISION_SNAPSHOT,
        )
        assert step_follows(
            "raes-range",
            "provision",
            previous=ResultStep.RAES_PROVISION_SNAPSHOT,
            step=ResultStep.RAES_TERMINAL_READY,
        )

    def test_progress_may_not_regress_after_a_terminal(self):
        assert not step_follows(
            "raes-range",
            "provision",
            previous=ResultStep.RAES_TERMINAL_READY,
            step=ResultStep.RAES_PROVISION_RUNNING,
        )

    def test_failure_may_not_overwrite_a_terminal_success(self):
        assert not step_follows(
            "raes-range",
            "provision",
            previous=ResultStep.RAES_TERMINAL_READY,
            step=ResultStep.RAES_TERMINAL_FAILED,
        )

    def test_a_terminal_replay_is_legal(self):
        assert step_follows(
            "raes-range",
            "destroy",
            previous=ResultStep.RAES_TERMINAL_DESTROYED,
            step=ResultStep.RAES_TERMINAL_DESTROYED,
        )

    def test_latest_step_uses_the_high_water_mark(self):
        assert (
            latest_step(
                "raes-range",
                "provision",
                [ResultStep.RAES_PROVISION_SNAPSHOT, ResultStep.RAES_PROVISION_RUNNING],
            )
            is ResultStep.RAES_PROVISION_SNAPSHOT
        )

    def test_terminal_outranks_a_same_rank_peer(self):
        assert (
            latest_step("raes-range", "destroy", [ResultStep.RAES_TERMINAL_DESTROYED, ResultStep.RAES_DESTROY_RUNNING])
            is ResultStep.RAES_TERMINAL_DESTROYED
        )


class TestIdentityIsRetryStable:
    def test_same_semantic_step_reproduces_one_identity(self):
        # No wall clock in the payload: a retried run must collapse onto the same
        # inbox row rather than landing as a conflicting sibling.
        first = parse_result_payload(
            "raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT, payload=_snapshot_payload()
        )
        second = parse_result_payload(
            "raes-range", "provision", step=ResultStep.RAES_PROVISION_SNAPSHOT, payload=_snapshot_payload()
        )
        assert first == second

        from shared.operation_envelope import canonical_payload_digest

        identity = build_result_identity(
            operation_id=_OPERATION_ID,
            step=ResultStep.RAES_PROVISION_SNAPSHOT,
            digest=canonical_payload_digest(first),
        )
        replay = build_result_identity(
            operation_id=_OPERATION_ID,
            step=ResultStep.RAES_PROVISION_SNAPSHOT,
            digest=canonical_payload_digest(second),
        )
        assert identity == replay
