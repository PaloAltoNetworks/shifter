"""Tests for experiment Pydantic schemas."""

import pytest
from pydantic import ValidationError

from experiments.schemas import (
    EXPERIMENT_TRANSITIONS,
    RUN_TRANSITIONS,
    ExperimentCreateInput,
    ExperimentStatus,
    RunStatus,
    ScriptAssignmentInput,
    ScriptType,
    ScriptUploadInput,
)


class TestScriptUploadInput:
    def test_valid_upload(self):
        data = ScriptUploadInput(name="My Script", filename="attack.py", file_size=1024)
        assert data.name == "My Script"
        assert data.filename == "attack.py"

    def test_rejects_non_python(self):
        with pytest.raises(ValidationError, match="Only .py files"):
            ScriptUploadInput(name="Bad", filename="attack.sh", file_size=100)

    def test_rejects_oversized(self):
        with pytest.raises(ValidationError, match="exceeds maximum"):
            ScriptUploadInput(name="Big", filename="big.py", file_size=2 * 1024 * 1024)

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            ScriptUploadInput(name="", filename="ok.py", file_size=100)

    def test_rejects_zero_size(self):
        with pytest.raises(ValidationError):
            ScriptUploadInput(name="Ok", filename="ok.py", file_size=0)


class TestScriptAssignmentInput:
    def test_python_requires_script_id(self):
        with pytest.raises(ValidationError, match="script_id is required"):
            ScriptAssignmentInput(
                instance_name="Workstation",
                script_type=ScriptType.PYTHON,
            )

    def test_claude_requires_prompt(self):
        with pytest.raises(ValidationError, match="claude_prompt is required"):
            ScriptAssignmentInput(
                instance_name="Attacker",
                script_type=ScriptType.CLAUDE_CODE,
            )

    def test_valid_python_assignment(self):
        data = ScriptAssignmentInput(
            instance_name="Workstation",
            script_type=ScriptType.PYTHON,
            script_id=1,
        )
        assert data.execution_order == 0

    def test_valid_claude_assignment(self):
        data = ScriptAssignmentInput(
            instance_name="Attacker",
            script_type=ScriptType.CLAUDE_CODE,
            claude_prompt="Attack {{Workstation.ip}}",
            execution_order=100,
        )
        assert data.claude_prompt == "Attack {{Workstation.ip}}"


class TestExperimentCreateInput:
    def test_valid_experiment(self):
        data = ExperimentCreateInput(
            name="Test Experiment",
            scenario_id="basic",
            total_runs=5,
            max_parallel_runs=3,
        )
        assert data.total_runs == 5

    def test_parallel_cannot_exceed_total(self):
        with pytest.raises(ValidationError, match="cannot exceed total_runs"):
            ExperimentCreateInput(
                name="Bad",
                scenario_id="basic",
                total_runs=2,
                max_parallel_runs=5,
            )

    def test_runs_max_10(self):
        with pytest.raises(ValidationError):
            ExperimentCreateInput(
                name="Too Many",
                scenario_id="basic",
                total_runs=11,
            )

    def test_parallel_max_5(self):
        with pytest.raises(ValidationError):
            ExperimentCreateInput(
                name="Too Parallel",
                scenario_id="basic",
                total_runs=10,
                max_parallel_runs=6,
            )

    def test_defaults(self):
        data = ExperimentCreateInput(name="Default", scenario_id="basic")
        assert data.total_runs == 1
        assert data.max_parallel_runs == 1
        assert data.description == ""
        assert data.scripts == []


class TestStateTransitions:
    def test_experiment_draft_to_queued(self):
        assert ExperimentStatus.QUEUED in EXPERIMENT_TRANSITIONS[ExperimentStatus.DRAFT]

    def test_experiment_running_terminal_states(self):
        allowed = EXPERIMENT_TRANSITIONS[ExperimentStatus.RUNNING]
        assert ExperimentStatus.COMPLETED in allowed
        assert ExperimentStatus.CANCELLED in allowed
        assert ExperimentStatus.FAILED in allowed

    def test_experiment_terminal_states_have_no_transitions(self):
        for status in [ExperimentStatus.COMPLETED, ExperimentStatus.CANCELLED, ExperimentStatus.FAILED]:
            assert EXPERIMENT_TRANSITIONS[status] == set()

    def test_run_full_happy_path(self):
        path = [
            RunStatus.PENDING,
            RunStatus.PROVISIONING,
            RunStatus.EXECUTING_VICTIMS,
            RunStatus.EXECUTING_ATTACKER,
            RunStatus.COLLECTING,
            RunStatus.COMPLETED,
        ]
        for i in range(len(path) - 1):
            assert path[i + 1] in RUN_TRANSITIONS[path[i]]

    def test_any_run_state_can_fail(self):
        for status in RunStatus:
            if status not in {RunStatus.COMPLETED, RunStatus.FAILED}:
                assert RunStatus.FAILED in RUN_TRANSITIONS[status]
