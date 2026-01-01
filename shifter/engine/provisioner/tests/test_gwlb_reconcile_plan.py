"""Tests for GWLBReconcilePlan - TDD: Write tests first, all must fail initially.

GWLBReconcilePlan handles drift detection between DB and VPC endpoints using AWSExecutor:
- Describe endpoints via AWSExecutor.describe_endpoints()
- Compare DB endpoints vs actual VPC endpoints
- Identify orphaned endpoints for cleanup

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from typing import List
from unittest.mock import MagicMock

import pytest


@dataclass
class MockGWLBReconcileInstance:
    """Mock instance for testing get_context."""

    service_name: str = "com.amazonaws.vpce.us-east-2.vpce-svc-12345"
    known_endpoint_ids: List[str] = None

    def __post_init__(self):
        if self.known_endpoint_ids is None:
            self.known_endpoint_ids = ["vpce-11111", "vpce-22222"]


class TestGWLBReconcilePlanSteps:
    """Test GWLBReconcilePlan step definitions."""

    def test_has_expected_steps(self):
        """GWLBReconcilePlan should have describe endpoints step."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert len(plan.steps) >= 1

    def test_has_describe_endpoints_step(self):
        """Plan should include describe endpoints step."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        step_names = [s.name for s in plan.steps]
        assert any("describe" in name.lower() or "endpoint" in name.lower() for name in step_names)

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestGWLBReconcilePlanAWSExecutorActions:
    """Test GWLBReconcilePlan uses AWSExecutor method names."""

    def test_describe_step_uses_describe_endpoints_action(self):
        """Describe step should use AWSExecutor.describe_endpoints action."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "endpoint" in s.name.lower())

        assert describe_step.action == "describe_endpoints"

    def test_describe_step_params_include_service_name(self):
        """Describe step params should include service_name."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "endpoint" in s.name.lower())

        assert "service_name" in describe_step.params


class TestGWLBReconcilePlanContext:
    """Test GWLBReconcilePlan.get_context method."""

    def test_get_context_returns_service_name(self):
        """get_context should return service_name."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance(service_name="com.amazonaws.vpce.test")
        context = plan.get_context(instance)

        assert "service_name" in context
        assert context["service_name"] == "com.amazonaws.vpce.test"

    def test_get_context_returns_known_endpoint_ids(self):
        """get_context should return known_endpoint_ids as list."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance(known_endpoint_ids=["vpce-99999"])
        context = plan.get_context(instance)

        assert "known_endpoint_ids" in context
        assert context["known_endpoint_ids"] == ["vpce-99999"]

    def test_get_context_missing_service_name_raises(self):
        """get_context should raise if service_name is missing."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance()
        instance.service_name = None

        with pytest.raises(ValueError, match="service_name"):
            plan.get_context(instance)

    def test_get_context_empty_known_endpoint_ids_allowed(self):
        """get_context should allow empty known_endpoint_ids list."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance(known_endpoint_ids=[])
        context = plan.get_context(instance)

        assert context["known_endpoint_ids"] == []


class TestGWLBReconcilePlanInterface:
    """Test GWLBReconcilePlan interface compliance."""

    def test_has_steps_attribute(self):
        """GWLBReconcilePlan should have steps attribute."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """GWLBReconcilePlan should have name attribute."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert hasattr(plan, "name")
        assert plan.name == "gwlb_reconcile"

    def test_has_get_context_method(self):
        """GWLBReconcilePlan should have get_context method."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestGWLBReconcilePlanExecution:
    """Test GWLBReconcilePlan can be executed with AWSExecutor."""

    def test_execute_describe_step_calls_aws_executor(self):
        """Execute describe step should call AWSExecutor.describe_endpoints."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        describe_step = next(s for s in plan.steps if "describe" in s.name.lower() or "endpoint" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.describe_endpoints.return_value = MagicMock(
            success=True,
            stdout='{"VpcEndpoints": [{"VpcEndpointId": "vpce-12345", "State": "available"}]}',
            stderr="",
        )

        # Build params from context
        context = {"service_name": "com.amazonaws.vpce.test"}
        params = {k: context[k] for k in describe_step.params}

        # Call the executor method
        method = getattr(mock_executor, describe_step.action)
        result = method(**params)

        mock_executor.describe_endpoints.assert_called_once_with(service_name="com.amazonaws.vpce.test")
        assert result.success is True
