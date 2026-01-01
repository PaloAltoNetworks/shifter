"""Tests for GWLBRemoveRoutePlan - TDD: Write tests first, all must fail initially.

GWLBRemoveRoutePlan handles removing GWLB routing when a range is destroyed using AWSExecutor:
- Delete route via AWSExecutor.delete_route()
- Delete VPC endpoint via AWSExecutor.delete_endpoint()

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockRemoveRouteInstance:
    """Mock instance for testing get_context."""

    endpoint_id: str = "vpce-12345"
    route_table_id: str = "rtb-12345"


class TestGWLBRemoveRoutePlanSteps:
    """Test GWLBRemoveRoutePlan step definitions."""

    def test_has_expected_steps(self):
        """GWLBRemoveRoutePlan should have route removal and endpoint deletion steps."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        assert len(plan.steps) >= 2

    def test_has_delete_route_step(self):
        """Plan should include route deletion step."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        step_names = [s.name for s in plan.steps]
        assert any("route" in name.lower() for name in step_names)

    def test_has_delete_endpoint_step(self):
        """Plan should include endpoint deletion step."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        step_names = [s.name for s in plan.steps]
        assert any("endpoint" in name.lower() for name in step_names)

    def test_route_before_endpoint(self):
        """Route deletion must come before endpoint deletion."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        step_names = [s.name for s in plan.steps]

        route_idx = next(i for i, n in enumerate(step_names) if "route" in n.lower())
        endpoint_idx = next(i for i, n in enumerate(step_names) if "endpoint" in n.lower())
        assert route_idx < endpoint_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestGWLBRemoveRoutePlanAWSExecutorActions:
    """Test GWLBRemoveRoutePlan uses AWSExecutor method names."""

    def test_delete_route_step_uses_delete_route_action(self):
        """Delete route step should use AWSExecutor.delete_route action."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        assert route_step.action == "delete_route"

    def test_delete_route_params_include_required_fields(self):
        """Delete route params should include route_table_id and destination."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        assert "route_table_id" in route_step.params
        assert "destination" in route_step.params

    def test_delete_endpoint_step_uses_delete_endpoint_action(self):
        """Delete endpoint step should use AWSExecutor.delete_endpoint action."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        assert endpoint_step.action == "delete_endpoint"

    def test_delete_endpoint_params_include_endpoint_id(self):
        """Delete endpoint params should include endpoint_id."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        assert "endpoint_id" in endpoint_step.params


class TestGWLBRemoveRoutePlanContext:
    """Test GWLBRemoveRoutePlan.get_context method."""

    def test_get_context_returns_endpoint_id(self):
        """get_context should return endpoint_id."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance(endpoint_id="vpce-99999")
        context = plan.get_context(instance)

        assert "endpoint_id" in context
        assert context["endpoint_id"] == "vpce-99999"

    def test_get_context_returns_route_table_id(self):
        """get_context should return route_table_id."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance(route_table_id="rtb-99999")
        context = plan.get_context(instance)

        assert "route_table_id" in context
        assert context["route_table_id"] == "rtb-99999"

    def test_get_context_returns_default_destination(self):
        """get_context should return destination as 0.0.0.0/0."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance()
        context = plan.get_context(instance)

        assert "destination" in context
        assert context["destination"] == "0.0.0.0/0"

    def test_get_context_missing_endpoint_id_raises(self):
        """get_context should raise if endpoint_id is missing."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance()
        instance.endpoint_id = None

        with pytest.raises(ValueError, match="endpoint_id"):
            plan.get_context(instance)

    def test_get_context_missing_route_table_id_raises(self):
        """get_context should raise if route_table_id is missing."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        instance = MockRemoveRouteInstance()
        instance.route_table_id = None

        with pytest.raises(ValueError, match="route_table_id"):
            plan.get_context(instance)


class TestGWLBRemoveRoutePlanInterface:
    """Test GWLBRemoveRoutePlan interface compliance."""

    def test_has_steps_attribute(self):
        """GWLBRemoveRoutePlan should have steps attribute."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """GWLBRemoveRoutePlan should have name attribute."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        assert hasattr(plan, "name")
        assert plan.name == "gwlb_remove_route"

    def test_has_get_context_method(self):
        """GWLBRemoveRoutePlan should have get_context method."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestGWLBRemoveRoutePlanExecution:
    """Test GWLBRemoveRoutePlan can be executed with AWSExecutor."""

    def test_execute_delete_route_step_calls_aws_executor(self):
        """Execute delete route step should call AWSExecutor.delete_route."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.delete_route.return_value = MagicMock(success=True, stdout="{}", stderr="")

        # Build params from context
        context = {
            "route_table_id": "rtb-12345",
            "destination": "0.0.0.0/0",
        }
        params = {k: context[k] for k in route_step.params}

        # Call the executor method
        method = getattr(mock_executor, route_step.action)
        result = method(**params)

        mock_executor.delete_route.assert_called_once_with(
            route_table_id="rtb-12345",
            destination="0.0.0.0/0",
        )
        assert result.success is True

    def test_execute_delete_endpoint_step_calls_aws_executor(self):
        """Execute delete endpoint step should call AWSExecutor.delete_endpoint."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.delete_endpoint.return_value = MagicMock(success=True, stdout="{}", stderr="")

        # Build params from context
        context = {"endpoint_id": "vpce-12345"}
        params = {k: context[k] for k in endpoint_step.params}

        # Call the executor method
        method = getattr(mock_executor, endpoint_step.action)
        result = method(**params)

        mock_executor.delete_endpoint.assert_called_once_with(endpoint_id="vpce-12345")
        assert result.success is True
