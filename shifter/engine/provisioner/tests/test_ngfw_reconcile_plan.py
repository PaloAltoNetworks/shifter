"""Tests for NGFWReconcilePlan.

NGFWReconcilePlan handles drift detection between DB and EC2 using AWSExecutor.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from plans.ngfw_reconcile import NGFWReconcilePlan


@dataclass
class MockNGFWReconcileInstance:
    """Mock instance for testing get_context."""

    instance_ids: list[str] = None

    def __post_init__(self):
        if self.instance_ids is None:
            self.instance_ids = ["i-12345", "i-67890"]


class TestNGFWReconcilePlan:
    """Tests for NGFWReconcilePlan behavior."""

    def test_describe_step_uses_correct_action(self):
        """Describe step uses describe_instances action."""
        plan = NGFWReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())
        assert describe_step.action == "describe_instances"
        assert "instance_ids" in describe_step.params


class TestNGFWReconcilePlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_instance_ids(self):
        """get_context returns instance_ids."""
        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance(instance_ids=["i-11111", "i-22222"])
        context = plan.get_context(instance)

        assert context["instance_ids"] == ["i-11111", "i-22222"]

    def test_get_context_missing_instance_ids_raises(self):
        """get_context raises if instance_ids is missing."""
        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance()
        instance.instance_ids = None

        with pytest.raises(ValueError, match="instance_ids"):
            plan.get_context(instance)

    def test_get_context_empty_instance_ids_allowed(self):
        """get_context allows empty instance_ids list."""
        plan = NGFWReconcilePlan()
        instance = MockNGFWReconcileInstance(instance_ids=[])
        context = plan.get_context(instance)

        assert context["instance_ids"] == []


class TestNGFWReconcilePlanExecution:
    """Tests for plan execution with AWSExecutor."""

    def test_execute_describe_step_calls_aws_executor(self):
        """Describe step calls AWSExecutor.describe_instances."""
        plan = NGFWReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "instance" in s.name.lower())

        mock_executor = MagicMock()
        mock_executor.describe_instances.return_value = MagicMock(
            success=True,
            stdout='{"Reservations": [{"Instances": [{"InstanceId": "i-12345"}]}]}',
            stderr="",
        )

        context = {"instance_ids": ["i-12345", "i-67890"]}
        params = {k: context[k] for k in describe_step.params}

        method = getattr(mock_executor, describe_step.action)
        result = method(**params)

        mock_executor.describe_instances.assert_called_once_with(instance_ids=["i-12345", "i-67890"])
        assert result.success is True
