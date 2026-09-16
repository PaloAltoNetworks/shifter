"""Tests for RangeResumePlan - starting a stopped range instance.

RangeResumePlan handles starting a single range instance using AWSExecutor:
- Start EC2 instance via AWSExecutor.start_instance()
- Wait for running state via AWSExecutor.wait_for_running()

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

import pytest

from executors.aws_executor import AWSExecutor


class TestRangeResumePlanSteps:
    """Test RangeResumePlan step definitions."""

    def test_has_expected_steps(self):
        """RangeResumePlan should have start and wait steps."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        assert len(plan.steps) >= 2

    def test_has_start_instance_step(self):
        """Plan should include EC2 start step."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        step_names = [s.name for s in plan.steps]
        assert any("start" in name.lower() for name in step_names)

    def test_has_wait_running_step(self):
        """Plan should include wait for running step."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        step_names = [s.name for s in plan.steps]
        assert any("running" in name.lower() or "wait" in name.lower() for name in step_names)

    def test_start_before_wait(self):
        """Start must come before wait steps."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        step_names = [s.name for s in plan.steps]

        start_idx = next(i for i, n in enumerate(step_names) if "start" in n.lower())
        wait_idx = next(
            i
            for i, n in enumerate(step_names)
            if "running" in n.lower() or ("wait" in n.lower() and "start" not in n.lower())
        )
        assert start_idx < wait_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"


class TestRangeResumePlanAWSExecutorActions:
    """Test RangeResumePlan uses AWSExecutor method names."""

    def test_start_step_uses_start_instance_action(self):
        """Start step should use AWSExecutor.start_instance action."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        start_step = next(s for s in plan.steps if "start" in s.name.lower())

        assert start_step.action == "start_instance"

    def test_wait_step_uses_wait_for_running_action(self):
        """Wait step should use AWSExecutor.wait_for_running action."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        wait_step = next(s for s in plan.steps if "running" in s.name.lower() or "wait" in s.name.lower())

        assert wait_step.action == "wait_for_running"


class TestRangeResumePlanContext:
    """Test RangeResumePlan.get_context method."""

    def test_get_context_returns_instance_id(self):
        """get_context should return instance_id."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        context = plan.get_context("i-99999")

        assert "instance_id" in context
        assert context["instance_id"] == "i-99999"

    def test_get_context_missing_instance_id_raises(self):
        """get_context should raise if instance_id is missing."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context("")

    def test_get_context_none_instance_id_raises(self):
        """get_context should raise if instance_id is None."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context(None)


class TestRangeResumePlanInterface:
    """Test RangeResumePlan interface compliance."""

    def test_has_steps_attribute(self):
        """RangeResumePlan should have steps attribute."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """RangeResumePlan should have name attribute."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        assert hasattr(plan, "name")
        assert plan.name == "range_resume"

    def test_has_get_context_method(self):
        """RangeResumePlan should have get_context method."""
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestRangeResumePlanExecution:
    """Every plan step must be dispatchable through the action allowlist."""

    def test_steps_are_in_the_action_allowlist(self):
        """Each step names an action the AWSExecutor allowlist recognizes.

        ``execute_action`` returns an "Unknown action" result before any AWS
        call, so this runs offline and fails if a plan names an action the
        executor cannot dispatch (the allowlist is the single authority).
        """
        from plans.range_resume import RangeResumePlan

        executor = AWSExecutor(region_name="us-east-2")

        for step in RangeResumePlan().steps:
            result = executor.execute_action(step.action, {})
            assert not result.stderr.startswith("Unknown action"), (
                f"step {step.name!r} names action {step.action!r} which is not in the AWSExecutor allowlist"
            )
