"""Tests for GWLBSetupPlan - TDD: Write tests first, all must fail initially.

GWLBSetupPlan handles GWLB target registration after NGFW provisioning:
- Register NGFW data ENI as target using AWSExecutor.register_target()
- Wait for target to become healthy

This plan uses AWSExecutor for AWS API calls, not bash scripts.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


@dataclass
class MockGWLBInstance:
    """Mock GWLB instance for testing get_context."""

    target_group_arn: str = "arn:aws:elasticloadbalancing:us-east-2:123456789012:targetgroup/test"
    ngfw_data_eni_id: str = "eni-12345"
    ngfw_instance_id: str = "i-12345"


class TestGWLBSetupPlanSteps:
    """Test GWLBSetupPlan step definitions."""

    def test_has_expected_steps(self):
        """GWLBSetupPlan should have target registration and health check steps."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert len(plan.steps) >= 2

    def test_has_register_target_step(self):
        """Plan should include target registration step."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        step_names = [s.name for s in plan.steps]
        assert any("register" in name.lower() for name in step_names)

    def test_has_wait_healthy_step(self):
        """Plan should include wait for healthy step."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        step_names = [s.name for s in plan.steps]
        assert any("health" in name.lower() or "wait" in name.lower() for name in step_names)

    def test_register_before_health_check(self):
        """Target registration must come before health check."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        step_names = [s.name for s in plan.steps]

        register_idx = next(i for i, n in enumerate(step_names) if "register" in n.lower())
        health_idx = next(i for i, n in enumerate(step_names) if "health" in n.lower() or "wait" in n.lower())
        assert register_idx < health_idx

    def test_all_steps_have_names(self):
        """All steps must have names."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_action(self):
        """All steps must have action attribute (AWSExecutor method name)."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        for step in plan.steps:
            assert hasattr(step, "action"), f"Step {step.name} must have action attribute"
            assert step.action, f"Step {step.name} must have non-empty action"

    def test_all_steps_have_params(self):
        """All steps must have params attribute (context keys to pass)."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        for step in plan.steps:
            assert hasattr(step, "params"), f"Step {step.name} must have params attribute"


class TestGWLBSetupPlanAWSExecutorActions:
    """Test GWLBSetupPlan uses AWSExecutor method names."""

    def test_register_step_uses_register_target_action(self):
        """Register step should use AWSExecutor.register_target action."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        register_step = next(s for s in plan.steps if "register" in s.name.lower())

        assert register_step.action == "register_target"

    def test_register_step_params_include_target_group_arn(self):
        """Register step params should include target_group_arn."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        register_step = next(s for s in plan.steps if "register" in s.name.lower())

        assert "target_group_arn" in register_step.params

    def test_register_step_params_include_target_id(self):
        """Register step params should include target_id."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        register_step = next(s for s in plan.steps if "register" in s.name.lower())

        assert "target_id" in register_step.params

    def test_wait_healthy_step_uses_describe_target_health_action(self):
        """Wait healthy step should use appropriate AWSExecutor action."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        health_step = next(s for s in plan.steps if "health" in s.name.lower() or "wait" in s.name.lower())

        # Should use wait_for_target_healthy or describe_target_health
        valid_actions = ["wait_for_target_healthy", "describe_target_health"]
        assert health_step.action in valid_actions, f"Expected one of {valid_actions}, got {health_step.action}"


class TestGWLBSetupPlanContext:
    """Test GWLBSetupPlan.get_context method."""

    def test_get_context_returns_target_group_arn(self):
        """get_context should return target_group_arn."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance(target_group_arn="arn:aws:test")
        context = plan.get_context(instance)

        assert "target_group_arn" in context
        assert context["target_group_arn"] == "arn:aws:test"

    def test_get_context_returns_target_id(self):
        """get_context should return target ID (ENI or instance)."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance(ngfw_data_eni_id="eni-99999")
        context = plan.get_context(instance)

        assert "target_id" in context

    def test_get_context_prefers_eni_over_instance(self):
        """get_context should prefer data ENI ID over instance ID for GWLB target."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance(ngfw_data_eni_id="eni-99999", ngfw_instance_id="i-12345")
        context = plan.get_context(instance)

        # GWLB targets should use ENI for traffic inspection
        assert context["target_id"] == "eni-99999"

    def test_get_context_missing_target_group_raises(self):
        """get_context should raise if target_group_arn is missing."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance()
        instance.target_group_arn = None

        with pytest.raises(ValueError, match="target_group"):
            plan.get_context(instance)

    def test_get_context_missing_target_id_raises(self):
        """get_context should raise if both ENI and instance ID are missing."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        instance = MockGWLBInstance()
        instance.ngfw_data_eni_id = None
        instance.ngfw_instance_id = None

        with pytest.raises(ValueError, match="target"):
            plan.get_context(instance)


class TestGWLBSetupPlanInterface:
    """Test GWLBSetupPlan interface compliance."""

    def test_has_steps_attribute(self):
        """GWLBSetupPlan should have steps attribute."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_name_attribute(self):
        """GWLBSetupPlan should have name attribute."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert hasattr(plan, "name")
        assert plan.name == "gwlb_setup"

    def test_has_get_context_method(self):
        """GWLBSetupPlan should have get_context method."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)


class TestGWLBSetupPlanExecution:
    """Test GWLBSetupPlan can be executed with AWSExecutor."""

    def test_execute_register_step_calls_aws_executor(self):
        """Execute register step should call AWSExecutor.register_target."""
        from plans.gwlb_setup import GWLBSetupPlan

        plan = GWLBSetupPlan()
        register_step = next(s for s in plan.steps if "register" in s.name.lower())

        # Mock AWSExecutor
        mock_executor = MagicMock()
        mock_executor.register_target.return_value = MagicMock(success=True, stdout="{}", stderr="")

        # Build params from context
        context = {
            "target_group_arn": "arn:aws:test",
            "target_id": "eni-12345",
        }
        params = {k: context[k] for k in register_step.params}

        # Call the executor method
        method = getattr(mock_executor, register_step.action)
        result = method(**params)

        mock_executor.register_target.assert_called_once_with(
            target_group_arn="arn:aws:test",
            target_id="eni-12345",
        )
        assert result.success is True
