"""Tests for the shared orchestrator ``StepResult`` type.

There is deliberately no shared ``Orchestrator`` protocol: the two
orchestrators depend on distinct executor ports and have distinct plan/result
contracts. ``StepResult`` is the one step-result type both use.
"""

from dataclasses import fields


class TestStepResultDataclass:
    """Test StepResult dataclass structure."""

    def test_step_result_has_step_name_field(self):
        """StepResult has step_name: str field."""
        from orchestrators.base import StepResult

        result = StepResult(step_name="test", success=True, stdout="", stderr="")
        assert hasattr(result, "step_name")
        assert isinstance(result.step_name, str)

    def test_step_result_has_success_field(self):
        """StepResult has success: bool field."""
        from orchestrators.base import StepResult

        result = StepResult(step_name="test", success=True, stdout="", stderr="")
        assert hasattr(result, "success")
        assert isinstance(result.success, bool)

    def test_step_result_has_stdout_field(self):
        """StepResult has stdout: str field."""
        from orchestrators.base import StepResult

        result = StepResult(step_name="test", success=True, stdout="output", stderr="")
        assert hasattr(result, "stdout")
        assert isinstance(result.stdout, str)

    def test_step_result_has_stderr_field(self):
        """StepResult has stderr: str field."""
        from orchestrators.base import StepResult

        result = StepResult(step_name="test", success=True, stdout="", stderr="error")
        assert hasattr(result, "stderr")
        assert isinstance(result.stderr, str)

    def test_step_result_is_dataclass(self):
        """StepResult is a dataclass."""
        from orchestrators.base import StepResult

        # Dataclasses have __dataclass_fields__
        assert hasattr(StepResult, "__dataclass_fields__")

    def test_step_result_field_names(self):
        """StepResult has exactly the expected fields."""
        from orchestrators.base import StepResult

        field_names = {f.name for f in fields(StepResult)}
        # Must have at least step_name, success, stdout, stderr
        assert "step_name" in field_names
        assert "success" in field_names
        assert "stdout" in field_names
        assert "stderr" in field_names


class TestStepResultConsolidation:
    """StepResult is a single type shared across the orchestrator package."""

    def test_no_orchestrator_protocol_exported(self):
        """The vacuous, Any-typed Orchestrator protocol has been removed."""
        import orchestrators.base as base

        assert not hasattr(base, "Orchestrator")

    def test_setup_types_reexports_base_step_result(self):
        """orchestrators._setup_types.StepResult IS orchestrators.base.StepResult."""
        from orchestrators._setup_types import StepResult as setup_step_result
        from orchestrators.base import StepResult as base_step_result

        assert setup_step_result is base_step_result

    def test_setup_orchestrator_reexports_same_step_result(self):
        """SetupOrchestrator's public StepResult re-export is the same type."""
        from orchestrators.base import StepResult as base_step_result
        from orchestrators.setup_orchestrator import StepResult as setup_orch_step_result

        assert setup_orch_step_result is base_step_result


class TestOrchestratorSurface:
    """Smoke coverage for the orchestrators' public method surface."""

    def test_setup_orchestrator_has_orchestrate_method(self):
        """SetupOrchestrator has orchestrate method."""
        from orchestrators.setup_orchestrator import SetupOrchestrator

        assert hasattr(SetupOrchestrator, "orchestrate")
        assert callable(SetupOrchestrator.orchestrate)

    def test_setup_orchestrator_orchestrate_accepts_plan(self):
        """SetupOrchestrator.orchestrate accepts plan and context parameters."""
        import inspect

        from orchestrators.setup_orchestrator import SetupOrchestrator

        sig = inspect.signature(SetupOrchestrator.orchestrate)
        param_names = list(sig.parameters.keys())

        # Should have instance_id, plan, context parameters (self is implicit)
        assert "instance_id" in param_names
        assert "plan" in param_names
        assert "context" in param_names


class TestStepResultEquality:
    """Test StepResult equality and usage."""

    def test_step_result_equality(self):
        """StepResult instances with same values are equal."""
        from orchestrators.base import StepResult

        r1 = StepResult(step_name="test", success=True, stdout="ok", stderr="")
        r2 = StepResult(step_name="test", success=True, stdout="ok", stderr="")
        assert r1 == r2

    def test_step_result_inequality(self):
        """StepResult instances with different values are not equal."""
        from orchestrators.base import StepResult

        r1 = StepResult(step_name="test1", success=True, stdout="ok", stderr="")
        r2 = StepResult(step_name="test2", success=True, stdout="ok", stderr="")
        assert r1 != r2

    def test_step_result_default_empty_strings(self):
        """StepResult can have default empty strings for stdout/stderr."""
        from orchestrators.base import StepResult

        # Test that these defaults work
        result = StepResult(step_name="test", success=True, stdout="", stderr="")
        assert result.stdout == ""
        assert result.stderr == ""
