"""Tests for NGFWRemoveRulePlan.

NGFWRemoveRulePlan deletes a PAN-OS security rule.
Used by CMS when tearing down routing policies.
"""

from dataclasses import dataclass

import pytest


@dataclass
class MockRuleConfig:
    """Mock config for testing get_context."""

    rule_name: str = "dc-to-servers"
    management_ip: str = "10.0.4.10"


class TestNGFWRemoveRulePlanSteps:
    """Test NGFWRemoveRulePlan step definitions."""

    def test_has_one_step(self):
        """NGFWRemoveRulePlan should have 1 step."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert len(plan.steps) == 1

    def test_step_name_is_remove_rule(self):
        """Step should be named remove_rule."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert plan.steps[0].name == "remove_rule"

    def test_step_has_stdin_input(self):
        """Step must use stdin_input for PAN-OS configure mode."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert plan.steps[0].stdin_input, "Step must have stdin_input"

    def test_step_has_timeout(self):
        """Step must have positive timeout."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert plan.steps[0].timeout_seconds > 0


class TestNGFWRemoveRulePlanVerification:
    """Test NGFWRemoveRulePlan verification step."""

    def test_has_verification_step(self):
        """NGFWRemoveRulePlan should have a verification step."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert plan.verify_step is not None

    def test_verification_step_is_marked_as_verification(self):
        """Verification step should have is_verification=True."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert plan.verify_step.is_verification is True


class TestNGFWRemoveRulePlanContext:
    """Test NGFWRemoveRulePlan.get_context method."""

    def test_get_context_returns_rule_name(self):
        """get_context should return rule_name."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        config = MockRuleConfig(rule_name="servers-to-workstations")
        context = plan.get_context(config)

        assert "rule_name" in context
        assert context["rule_name"] == "servers-to-workstations"

    def test_get_context_returns_management_ip(self):
        """get_context should return management_ip."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        config = MockRuleConfig(management_ip="10.0.4.50")
        context = plan.get_context(config)

        assert "management_ip" in context
        assert context["management_ip"] == "10.0.4.50"

    def test_get_context_missing_rule_name_raises(self):
        """get_context should raise if rule_name is missing."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        config = MockRuleConfig()
        config.rule_name = None

        with pytest.raises(ValueError, match="rule_name"):
            plan.get_context(config)

    def test_get_context_missing_management_ip_raises(self):
        """get_context should raise if management_ip is missing."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        config = MockRuleConfig()
        config.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(config)


class TestNGFWRemoveRulePlanScripts:
    """Test NGFWRemoveRulePlan script content."""

    def test_stdin_input_deletes_security_rule(self):
        """stdin_input should delete security rule."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        content = plan.steps[0].stdin_input

        assert "delete rulebase security rules" in content

    def test_stdin_input_has_rule_name_template(self):
        """stdin_input should have {{ rule_name }} template variable."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        content = plan.steps[0].stdin_input

        assert "{{ rule_name }}" in content

    def test_stdin_input_includes_commit(self):
        """stdin_input must include commit command."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        content = plan.steps[0].stdin_input

        assert "commit" in content.lower()

    def test_stdin_input_enters_configure_mode(self):
        """stdin_input must enter configure mode."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        content = plan.steps[0].stdin_input

        assert "configure" in content.lower()


class TestNGFWRemoveRulePlanInterface:
    """Test NGFWRemoveRulePlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWRemoveRulePlan should have steps attribute."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWRemoveRulePlan should have verify_step attribute."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWRemoveRulePlan should have get_context method."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)

    def test_has_name_attribute(self):
        """NGFWRemoveRulePlan should have name attribute."""
        from plans.ngfw_remove_rule import NGFWRemoveRulePlan

        plan = NGFWRemoveRulePlan()
        assert hasattr(plan, "name")
        assert plan.name == "ngfw_remove_rule"
