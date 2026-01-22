"""Tests for UserNGFWStackSweepPlan.

UserNGFWStackSweepPlan handles idle NGFW detection using AWSExecutor.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockSweepInstance:
    """Mock instance for testing get_context."""

    instance_ids: list[str] = None
    idle_threshold_minutes: int = 60

    def __post_init__(self):
        if self.instance_ids is None:
            self.instance_ids = ["i-12345", "i-67890"]


class TestUserNGFWStackSweepPlan:
    """Tests for UserNGFWStackSweepPlan behavior."""

    def test_describe_step_uses_correct_action(self):
        """Describe step uses describe_instances action with instance_ids param."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        assert describe_step.action == "describe_instances"
        assert "instance_ids" in describe_step.params


class TestUserNGFWStackSweepPlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_required_fields(self):
        """get_context returns instance_ids and idle_threshold_minutes."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance(instance_ids=["i-11111", "i-22222"], idle_threshold_minutes=120)
        context = plan.get_context(instance)

        assert context["instance_ids"] == ["i-11111", "i-22222"]
        assert context["idle_threshold_minutes"] == 120

    def test_get_context_missing_instance_ids_raises(self):
        """get_context raises if instance_ids is missing."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance()
        instance.instance_ids = None

        with pytest.raises(ValueError, match="instance_ids"):
            plan.get_context(instance)

    def test_get_context_empty_instance_ids_allowed(self):
        """get_context allows empty instance_ids list."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        instance = MockSweepInstance(instance_ids=[])
        context = plan.get_context(instance)

        assert context["instance_ids"] == []


class TestUserNGFWStackSweepPlanExecution:
    """Tests for plan execution with AWSExecutor."""

    def test_execute_describe_step_calls_aws_executor(self):
        """Describe step calls AWSExecutor.describe_instances."""
        from plans.user_ngfw_stack_sweep import UserNGFWStackSweepPlan

        plan = UserNGFWStackSweepPlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        mock_executor = MagicMock()
        mock_executor.describe_instances.return_value = MagicMock(
            success=True,
            stdout='{"Reservations": [{"Instances": [{"InstanceId": "i-12345", "State": {"Name": "running"}}]}]}',
            stderr="",
        )

        context = {"instance_ids": ["i-12345", "i-67890"]}
        params = {k: context[k] for k in describe_step.params}

        method = getattr(mock_executor, describe_step.action)
        result = method(**params)

        mock_executor.describe_instances.assert_called_once_with(instance_ids=["i-12345", "i-67890"])
        assert result.success is True
