"""Tests for GWLBRemoveRoutePlan - TDD: Write tests first, all must fail initially.

GWLBRemoveRoutePlan handles removing GWLB routing when a range is destroyed:
- Remove route from route table
- Delete VPC endpoint
"""

from dataclasses import dataclass
from typing import Optional

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

    def test_has_remove_route_step(self):
        """Plan should include route removal step."""
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
        """Route removal must come before endpoint deletion."""
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

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0


class TestGWLBRemoveRoutePlanScripts:
    """Test GWLBRemoveRoutePlan script content."""

    def test_remove_route_script_uses_aws_cli(self):
        """Route removal script should use AWS CLI."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        assert "aws" in route_step.script.lower()
        assert "delete-route" in route_step.script.lower()

    def test_remove_route_targets_default_route(self):
        """Route removal should target 0.0.0.0/0."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        route_step = next(s for s in plan.steps if "route" in s.name.lower())

        assert "0.0.0.0/0" in route_step.script

    def test_delete_endpoint_script_uses_aws_cli(self):
        """Endpoint deletion script should use AWS CLI."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        assert "aws" in endpoint_step.script.lower()
        assert "delete-vpc-endpoints" in endpoint_step.script.lower()

    def test_delete_endpoint_references_endpoint_id(self):
        """Endpoint deletion should reference endpoint ID."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        endpoint_step = next(s for s in plan.steps if "endpoint" in s.name.lower())

        assert "endpoint_id" in endpoint_step.script or "ENDPOINT_ID" in endpoint_step.script


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

    def test_has_verify_step_attribute(self):
        """GWLBRemoveRoutePlan should have verify_step attribute."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """GWLBRemoveRoutePlan should have get_context method."""
        from plans.gwlb_remove_route import GWLBRemoveRoutePlan

        plan = GWLBRemoveRoutePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
