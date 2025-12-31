"""Tests for GWLBReconcilePlan - TDD: Write tests first, all must fail initially.

GWLBReconcilePlan handles drift detection between DB and VPC endpoints:
- Compare DB endpoints vs actual VPC endpoints
- Detect orphan endpoints (in AWS but not in DB)
- Clean up orphaned resources
"""

from dataclasses import dataclass
from typing import Optional, List

import pytest


@dataclass
class MockGWLBReconcileInstance:
    """Mock instance for testing get_context."""

    service_name: str = "com.amazonaws.vpce.us-east-2.vpce-svc-12345"
    known_endpoint_ids: List[str] = None  # Endpoint IDs tracked in DB
    vpc_id: str = "vpc-12345"

    def __post_init__(self):
        if self.known_endpoint_ids is None:
            self.known_endpoint_ids = ["vpce-11111", "vpce-22222"]


class TestGWLBReconcilePlanSteps:
    """Test GWLBReconcilePlan step definitions."""

    def test_has_expected_steps(self):
        """GWLBReconcilePlan should have list and cleanup steps."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert len(plan.steps) >= 1

    def test_has_list_endpoints_step(self):
        """Plan should include endpoint listing step."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        step_names = [s.name for s in plan.steps]
        assert any("endpoint" in name.lower() or "list" in name.lower() for name in step_names)

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_scripts(self):
        """All steps must have script content."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        for step in plan.steps:
            assert step.script, f"Step {step.name} must have a script"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0


class TestGWLBReconcilePlanScripts:
    """Test GWLBReconcilePlan script content."""

    def test_list_script_uses_aws_cli(self):
        """List script should use AWS CLI for VPC endpoints."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        list_step = next(s for s in plan.steps if "endpoint" in s.name.lower() or "list" in s.name.lower())

        assert "aws" in list_step.script.lower()
        assert "describe-vpc-endpoints" in list_step.script.lower()

    def test_list_script_filters_by_service(self):
        """List script should filter by service name."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        list_step = next(s for s in plan.steps if "endpoint" in s.name.lower() or "list" in s.name.lower())

        assert "service_name" in list_step.script or "SERVICE_NAME" in list_step.script


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
        """get_context should return known_endpoint_ids."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance(known_endpoint_ids=["vpce-99999"])
        context = plan.get_context(instance)

        assert "known_endpoint_ids" in context

    def test_get_context_missing_service_name_raises(self):
        """get_context should raise if service_name is missing."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        instance = MockGWLBReconcileInstance()
        instance.service_name = None

        with pytest.raises(ValueError, match="service_name"):
            plan.get_context(instance)


class TestGWLBReconcilePlanInterface:
    """Test GWLBReconcilePlan interface compliance."""

    def test_has_steps_attribute(self):
        """GWLBReconcilePlan should have steps attribute."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """GWLBReconcilePlan should have verify_step attribute."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """GWLBReconcilePlan should have get_context method."""
        from plans.gwlb_reconcile import GWLBReconcilePlan

        plan = GWLBReconcilePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
