"""Tests for NGFWStartPlan.

NGFWStartPlan handles starting a stopped NGFW instance using AWSExecutor.
"""

from dataclasses import dataclass

import pytest

from executors.aws_executor import AWSExecutor
from plans.ngfw_start import NGFWStartPlan


@dataclass
class MockNGFWInstance:
    """Mock NGFW instance for testing get_context."""

    instance_id: str = "i-12345"


class TestNGFWStartPlan:
    """Tests for NGFWStartPlan behavior."""

    def test_steps_in_correct_order(self):
        """Start must come before wait for running."""
        plan = NGFWStartPlan()
        step_names = [s.name for s in plan.steps]

        start_idx = next(i for i, n in enumerate(step_names) if "start" in n.lower())
        wait_idx = next(i for i, n in enumerate(step_names) if "running" in n.lower() or "wait" in n.lower())
        assert start_idx < wait_idx

    def test_steps_use_correct_actions(self):
        """Steps use correct AWSExecutor actions."""
        plan = NGFWStartPlan()

        start_step = next(s for s in plan.steps if "start" in s.name.lower())
        assert start_step.action == "start_instance"

        wait_step = next(s for s in plan.steps if "running" in s.name.lower() or "wait" in s.name.lower())
        assert wait_step.action == "wait_for_running"


class TestNGFWStartPlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_instance_id(self):
        """get_context returns instance_id."""
        plan = NGFWStartPlan()
        instance = MockNGFWInstance(instance_id="i-99999")
        context = plan.get_context(instance)

        assert context["instance_id"] == "i-99999"

    def test_get_context_missing_instance_id_raises(self):
        """get_context raises if instance_id is missing."""
        plan = NGFWStartPlan()
        instance = MockNGFWInstance()
        instance.instance_id = None

        with pytest.raises(ValueError, match="instance_id"):
            plan.get_context(instance)


class TestNGFWStartPlanExecution:
    """Every plan step must be dispatchable through the action allowlist."""

    def test_steps_are_in_the_action_allowlist(self):
        """Each step names an action the AWSExecutor allowlist recognizes.

        The executor's ``execute_action`` allowlist is the single validation
        authority. An unknown action returns an "Unknown action" result before
        any AWS call, so this runs offline and would fail if a plan named an
        action the executor cannot dispatch.
        """
        executor = AWSExecutor(region_name="us-east-2")

        for step in NGFWStartPlan().steps:
            result = executor.execute_action(step.action, {})
            assert not result.stderr.startswith("Unknown action"), (
                f"step {step.name!r} names action {step.action!r} which is not in the AWSExecutor allowlist"
            )
