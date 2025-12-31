"""Tests for GWLBAddRoutePlan - TDD: Write tests first, all must fail initially.

GWLBAddRoutePlan handles adding GWLB routing for a new range:
- Create VPC endpoint in range subnet
- Update route table to send 0.0.0.0/0 through endpoint
"""

from dataclasses import dataclass
from typing import Optional

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
        assert len(plan.steps) >= 2

    def test_has_create_endpoint_step(self):
        """Plan should include VPC endpoint creation step."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        step_names = [s.name for s in plan.steps]
        assert any("endpoint" in name.lower() for name in step_names)

    def test_has_add_route_step(self):
        """Plan should include route table update step."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        step_names = [s.name for s in plan.steps]
        assert any("route" in name.lower() for name in step_names)

    def test_endpoint_before_route(self):
        """Endpoint creation must come before route update."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        step_names = [s.name for s in plan.steps]

        endpoint_idx = next(i for i, n in enumerate(step_names) if "endpoint" in n.lower())
        route_idx = next(i for i, n in enumerate(step_names) if "route" in n.lower() and "endpoint" not in n.lower())
        assert endpoint_idx < route_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0


class TestGWLBAddRoutePlanScripts:
    """Test GWLBAddRoutePlan script content."""

    def test_endpoint_script_uses_aws_cli(self):
        """Endpoint script should use AWS CLI for VPC endpoint creation."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        assert "aws" in endpoint_step.script.lower()
        assert "create-vpc-endpoint" in endpoint_step.script.lower()

    def test_endpoint_script_uses_gateway_load_balancer_type(self):
        """Endpoint should be GatewayLoadBalancer type."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        assert "GatewayLoadBalancer" in endpoint_step.script

    def test_endpoint_script_references_service_name(self):
        """Endpoint script should reference service name."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        assert "service_name" in endpoint_step.script or "SERVICE_NAME" in endpoint_step.script

    def test_route_script_uses_aws_cli(self):
        """Route script should use AWS CLI for route creation."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower() and "endpoint" not in s.name.lower())

        assert "aws" in route_step.script.lower()
        assert "create-route" in route_step.script.lower()

    def test_route_script_targets_default_route(self):
        """Route should target 0.0.0.0/0."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower() and "endpoint" not in s.name.lower())

        assert "0.0.0.0/0" in route_step.script


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

    def test_get_context_returns_subnet_id(self):
        """get_context should return subnet_id."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance(subnet_id="subnet-99999")
        context = plan.get_context(instance)

        assert "subnet_id" in context
        assert context["subnet_id"] == "subnet-99999"

    def test_get_context_returns_route_table_id(self):
        """get_context should return route_table_id."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        instance = MockRouteInstance(route_table_id="rtb-99999")
        context = plan.get_context(instance)

        assert "route_table_id" in context
        assert context["route_table_id"] == "rtb-99999"

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


class TestGWLBAddRoutePlanInterface:
    """Test GWLBAddRoutePlan interface compliance."""

    def test_has_steps_attribute(self):
        """GWLBAddRoutePlan should have steps attribute."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """GWLBAddRoutePlan should have verify_step attribute."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """GWLBAddRoutePlan should have get_context method."""
        from plans.gwlb_add_route import GWLBAddRoutePlan

        plan = GWLBAddRoutePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
