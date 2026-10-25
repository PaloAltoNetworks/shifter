"""Tests for RangeResumePlan - starting a stopped range instance.

RangeResumePlan handles starting a single range instance using AWSExecutor:
- Start EC2 instance via AWSExecutor.start_instance()
- Wait for running state via AWSExecutor.wait_for_running()

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

import pytest

from executors.aws_executor import AWSExecutor


class TestRangeResumePlanSteps:
    """The plan identifies itself and dispatches the lifecycle actions in order."""

    def test_named_steps_dispatch_expected_actions_in_order(self):
        from plans.range_resume import RangeResumePlan

        plan = RangeResumePlan()

        assert plan.name == "range_resume"
        assert [(step.name, step.action) for step in plan.steps] == [
            ("start_instance", "start_instance"),
            ("wait_for_running", "wait_for_running"),
        ]


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
