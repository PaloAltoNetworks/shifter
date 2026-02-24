"""Tests for NGFWStartPlan.

NGFWStartPlan handles starting a stopped NGFW instance using AWSExecutor.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

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
        assert "instance_id" in start_step.params

        wait_step = next(s for s in plan.steps if "running" in s.name.lower() or "wait" in s.name.lower())
        assert wait_step.action == "wait_for_running"
        assert "instance_id" in wait_step.params


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
    """Tests for plan execution with AWSExecutor."""

    def test_execute_steps_call_aws_executor(self):
        """Steps call correct AWSExecutor methods."""
        plan = NGFWStartPlan()

        mock_executor = MagicMock()
        mock_executor.start_instance.return_value = MagicMock(success=True)
        mock_executor.wait_for_running.return_value = MagicMock(success=True)

        context = {"instance_id": "i-12345"}

        # Execute start step
        start_step = next(s for s in plan.steps if "start" in s.name.lower())
        params = {k: context[k] for k in start_step.params}
        getattr(mock_executor, start_step.action)(**params)
        mock_executor.start_instance.assert_called_once_with(instance_id="i-12345")

        # Execute wait step
        wait_step = next(s for s in plan.steps if "running" in s.name.lower() or "wait" in s.name.lower())
        params = {k: context[k] for k in wait_step.params}
        getattr(mock_executor, wait_step.action)(**params)
        mock_executor.wait_for_running.assert_called_once_with(instance_id="i-12345")
