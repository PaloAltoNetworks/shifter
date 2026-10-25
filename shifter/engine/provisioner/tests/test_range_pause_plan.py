"""Tests for RangePausePlan - stopping a running range instance.

RangePausePlan handles stopping a single range instance using AWSExecutor:
- Stop EC2 instance via AWSExecutor.stop_instance()
- Wait for stopped state via AWSExecutor.wait_for_stopped()

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

import pytest

from executors.aws_executor import AWSExecutor


class TestRangePausePlanSteps:
    """The plan identifies itself and dispatches the lifecycle actions in order."""

    def test_named_steps_dispatch_expected_actions_in_order(self):
        from plans.range_pause import RangePausePlan

        plan = RangePausePlan()

        assert plan.name == "range_pause"
        assert [(step.name, step.action) for step in plan.steps] == [
            ("stop_instance", "stop_instance"),
            ("wait_for_stopped", "wait_for_stopped"),
        ]


class TestRangePausePlanContext:
    """Test RangePausePlan.get_context method."""

    def test_get_context_returns_instance_id(self):
        """get_context should return instance_id."""
        from plans.range_pause import RangePausePlan

        plan = RangePausePlan()
        context = plan.get_context("i-99999")

        assert "instance_id" in context
        assert context["instance_id"] == "i-99999"

    def test_get_context_missing_instance_id_raises(self):
        """get_context should raise if instance_id is missing."""
        from plans.range_pause import RangePausePlan

        plan = RangePausePlan()

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context("")

    def test_get_context_none_instance_id_raises(self):
        """get_context should raise if instance_id is None."""
        from plans.range_pause import RangePausePlan

        plan = RangePausePlan()

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context(None)


class TestRangePausePlanExecution:
    """Every plan step must be dispatchable through the action allowlist."""

    def test_steps_are_in_the_action_allowlist(self):
        """Each step names an action the AWSExecutor allowlist recognizes.

        ``execute_action`` returns an "Unknown action" result before any AWS
        call, so this runs offline and fails if a plan names an action the
        executor cannot dispatch (the allowlist is the single authority).
        """
        from plans.range_pause import RangePausePlan

        executor = AWSExecutor(region_name="us-east-2")

        for step in RangePausePlan().steps:
            result = executor.execute_action(step.action, {})
            assert not result.stderr.startswith("Unknown action"), (
                f"step {step.name!r} names action {step.action!r} which is not in the AWSExecutor allowlist"
            )
