"""Tests for GWLBAddRoutePlan - TDD: Write tests first, all must fail initially.

GWLBAddRoutePlan handles adding GWLB routing for a new range using AWSExecutor:
- Create VPC endpoint via AWSExecutor.create_endpoint()
- Wait for endpoint via AWSExecutor.wait_for_endpoint_available()
- Create route via AWSExecutor.create_route()

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockRouteInstance:
    """Mock instance for testing get_context."""

    service_name: str = "com.amazonaws.vpce.us-east-2.vpce-svc-12345"
    subnet_id: str = "subnet-12345"
    route_table_id: str = "rtb-12345"
    vpc_id: str = "vpc-12345"


class TestGWLBAddRoutePlanSteps:
    """Test GWLBAddRoutePlan step definitions."""

    def test_has_expected_steps(self):
        """GWLBAddRoutePlan should have endpoint and route steps."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        assert len(plan.steps) >= 3  # create_endpoint, wait, create_route

    def test_has_create_endpoint_step(self):
        """Plan should include VPC endpoint creation step."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        step_names = [s.name for s in plan.steps]
        assert any("endpoint" in name.lower() and "create" in name.lower() for name in step_names)

    def test_has_wait_endpoint_step(self):
        """Plan should include wait for endpoint step."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        step_names = [s.name for s in plan.steps]
        assert any("wait" in name.lower() or "available" in name.lower() for name in step_names)

    def test_has_create_route_step(self):
        """Plan should include route creation step."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        step_names = [s.name for s in plan.steps]
        assert any("route" in name.lower() for name in step_names)

    def test_endpoint_before_route(self):
        """Endpoint creation must come before route creation."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        step_names = [s.name for s in plan.steps]

        endpoint_idx = next(i for i, n in enumerate(step_names) if "endpoint" in n.lower() and "create" in n.lower())
        route_idx = next(i for i, n in enumerate(step_names) if "route" in n.lower())
        assert endpoint_idx < route_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestGWLBAddRoutePlanAWSExecutorActions:
    """Test GWLBAddRoutePlan uses AWSExecutor method names."""

    def test_create_endpoint_step_uses_create_endpoint_action(self):
        """Create endpoint step should use AWSExecutor.create_endpoint action."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower() and "create" in s.name.lower())

        assert endpoint_step.action == "create_endpoint"

    def test_create_endpoint_params_include_required_fields(self):
        """Create endpoint params should include vpc_id, service_name, subnet_ids."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower() and "create" in s.name.lower())

        assert "vpc_id" in endpoint_step.params
        assert "service_name" in endpoint_step.params
        assert "subnet_ids" in endpoint_step.params

    def test_wait_endpoint_step_uses_wait_action(self):
        """Wait step should use AWSExecutor.wait_for_endpoint_available action."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        wait_step = next(s for s in plan.steps if "wait" in s.name.lower() or "available" in s.name.lower())

        assert wait_step.action == "wait_for_endpoint_available"

    def test_create_route_step_uses_create_route_action(self):
        """Create route step should use AWSExecutor.create_route action."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        assert route_step.action == "create_route"

    def test_create_route_params_include_required_fields(self):
        """Create route params should include route_table_id, destination, endpoint_id."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        assert "route_table_id" in route_step.params
        assert "destination" in route_step.params
        assert "endpoint_id" in route_step.params


class TestGWLBAddRoutePlanContext:
    """Test GWLBAddRoutePlan.get_context method."""

    def test_get_context_returns_service_name(self):
        """get_context should return service_name."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance(service_name="com.amazonaws.vpce.test")
        context = plan.get_context(instance)

        assert "service_name" in context
        assert context["service_name"] == "com.amazonaws.vpce.test"

    def test_get_context_returns_subnet_ids(self):
        """get_context should return subnet_ids as list."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance(subnet_id="subnet-99999")
        context = plan.get_context(instance)

        assert "subnet_ids" in context
        assert context["subnet_ids"] == ["subnet-99999"]

    def test_get_context_returns_route_table_id(self):
        """get_context should return route_table_id."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance(route_table_id="rtb-99999")
        context = plan.get_context(instance)

        assert "route_table_id" in context
        assert context["route_table_id"] == "rtb-99999"

    def test_get_context_returns_vpc_id(self):
        """get_context should return vpc_id."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance(vpc_id="vpc-99999")
        context = plan.get_context(instance)

        assert "vpc_id" in context
        assert context["vpc_id"] == "vpc-99999"

    def test_get_context_returns_default_destination(self):
        """get_context should return destination as 0.0.0.0/0."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance()
        context = plan.get_context(instance)

        assert "destination" in context
        assert context["destination"] == "0.0.0.0/0"

    def test_get_context_missing_service_name_raises(self):
        """get_context should raise if service_name is missing."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance()
        instance.service_name = None

        with pytest.raises(ValueError, match="service_name"):
            plan.get_context(instance)

    def test_get_context_missing_subnet_id_raises(self):
        """get_context should raise if subnet_id is missing."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance()
        instance.subnet_id = None

        with pytest.raises(ValueError, match="subnet_id"):
            plan.get_context(instance)

    def test_get_context_missing_vpc_id_raises(self):
        """get_context should raise if vpc_id is missing."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance()
        instance.vpc_id = None

        with pytest.raises(ValueError, match="vpc_id"):
            plan.get_context(instance)


class TestGWLBAddRoutePlanInterface:
    """Test GWLBAddRoutePlan interface compliance."""

    def test_has_steps_attribute(self):
        """GWLBAddRoutePlan should have steps attribute."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """GWLBAddRoutePlan should have name attribute."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        assert hasattr(plan, "name")
        assert plan.name == "gwlb_add_route"

    def test_has_get_context_method(self):
        """GWLBAddRoutePlan should have get_context method."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestGWLBAddRoutePlanExecution:
    """Test GWLBAddRoutePlan can be executed with AWSExecutor."""

    def test_execute_create_endpoint_step_calls_aws_executor(self):
        """Execute create endpoint step should call AWSExecutor.create_endpoint."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower() and "create" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.create_endpoint.return_value = MagicMock(
            success=True, stdout='{"VpcEndpointId": "vpce-12345"}', stderr=""
        )

        # Build params from context
        context = {
            "vpc_id": "vpc-12345",
            "service_name": "com.amazonaws.vpce.test",
            "subnet_ids": ["subnet-12345"],
        }
        params = {k: context[k] for k in endpoint_step.params}

        # Call the executor method
        method = getattr(mock_executor, endpoint_step.action)
        result = method(**params)

        mock_executor.create_endpoint.assert_called_once()
        assert result.success is True

    def test_execute_create_route_step_calls_aws_executor(self):
        """Execute create route step should call AWSExecutor.create_route."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.create_route.return_value = MagicMock(success=True, stdout="{}", stderr="")

        # Build params from context
        context = {
            "route_table_id": "rtb-12345",
            "destination": "0.0.0.0/0",
            "endpoint_id": "vpce-12345",
        }
        params = {k: context[k] for k in route_step.params}

        # Call the executor method
        method = getattr(mock_executor, route_step.action)
        result = method(**params)

        mock_executor.create_route.assert_called_once_with(
            route_table_id="rtb-12345",
            destination="0.0.0.0/0",
            endpoint_id="vpce-12345",
        )
        assert result.success is True
