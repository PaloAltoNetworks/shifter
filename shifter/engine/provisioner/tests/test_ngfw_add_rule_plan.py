"""Tests for NGFWAddRulePlan.

NGFWAddRulePlan creates a PAN-OS security rule allowing traffic between
address objects (subnets). Used by CMS to configure routing policies.
"""

from dataclasses import dataclass

import pytest


@dataclass
class MockRuleConfig:
    """Mock config for testing get_context."""

    rule_name: str = "dc-to-servers"
    src_address: str = "dc-subnet"
    dst_address: str = "servers-subnet"
    management_ip: str = "10.0.4.10"


class TestNGFWAddRulePlanSteps:
    """Test NGFWAddRulePlan step definitions."""

    def test_has_one_step(self):
        """NGFWAddRulePlan should have 1 step."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert len(plan.steps) == 1

    def test_step_name_is_add_rule(self):
        """Step should be named add_rule."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert plan.steps[0].name == "add_rule"

    def test_step_has_stdin_input(self):
        """Step must use stdin_input for PAN-OS configure mode."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert plan.steps[0].stdin_input, "Step must have stdin_input"

    def test_step_has_timeout(self):
        """Step must have positive timeout."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert plan.steps[0].timeout_seconds > 0


class TestNGFWAddRulePlanVerification:
    """Test NGFWAddRulePlan verification step."""

    def test_has_verification_step(self):
        """NGFWAddRulePlan should have a verification step."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert plan.verify_step is not None

    def test_verification_step_is_marked_as_verification(self):
        """Verification step should have is_verification=True."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert plan.verify_step.is_verification is True


class TestNGFWAddRulePlanContext:
    """Test NGFWAddRulePlan.get_context method."""

    def test_get_context_returns_rule_name(self):
        """get_context should return rule_name."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig(rule_name="servers-to-workstations")
        context = plan.get_context(config)

        assert "rule_name" in context
        assert context["rule_name"] == "servers-to-workstations"

    def test_get_context_returns_src_address(self):
        """get_context should return src_address."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig(src_address="dc-subnet")
        context = plan.get_context(config)

        assert "src_address" in context
        assert context["src_address"] == "dc-subnet"

    def test_get_context_returns_dst_address(self):
        """get_context should return dst_address."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig(dst_address="servers-subnet")
        context = plan.get_context(config)

        assert "dst_address" in context
        assert context["dst_address"] == "servers-subnet"

    def test_get_context_returns_management_ip(self):
        """get_context should return management_ip."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig(management_ip="10.0.4.50")
        context = plan.get_context(config)

        assert "management_ip" in context
        assert context["management_ip"] == "10.0.4.50"

    def test_get_context_missing_rule_name_raises(self):
        """get_context should raise if rule_name is missing."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig()
        config.rule_name = None

        with pytest.raises(ValueError, match="rule_name"):
            plan.get_context(config)

    def test_get_context_missing_src_address_raises(self):
        """get_context should raise if src_address is missing."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig()
        config.src_address = None

        with pytest.raises(ValueError, match="src_address"):
            plan.get_context(config)

    def test_get_context_missing_dst_address_raises(self):
        """get_context should raise if dst_address is missing."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig()
        config.dst_address = None

        with pytest.raises(ValueError, match="dst_address"):
            plan.get_context(config)

    def test_get_context_missing_management_ip_raises(self):
        """get_context should raise if management_ip is missing."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        config = MockRuleConfig()
        config.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(config)


class TestNGFWAddRulePlanScripts:
    """Test NGFWAddRulePlan script content."""

    def test_stdin_input_sets_security_rule(self):
        """stdin_input should set security rule."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "rulebase security rules" in content

    def test_stdin_input_has_rule_name_template(self):
        """stdin_input should have {{ rule_name }} template variable."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "{{ rule_name }}" in content

    def test_stdin_input_has_src_address_template(self):
        """stdin_input should have {{ src_address }} template variable."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "{{ src_address }}" in content

    def test_stdin_input_has_dst_address_template(self):
        """stdin_input should have {{ dst_address }} template variable."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "{{ dst_address }}" in content

    def test_stdin_input_sets_action_allow(self):
        """stdin_input should set action to allow."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "action allow" in content

    def test_stdin_input_enables_logging(self):
        """stdin_input should enable logging."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "log-end yes" in content
        assert "XDR-Forward" in content

    def test_stdin_input_includes_commit(self):
        """stdin_input must include commit command."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "commit" in content.lower()

    def test_stdin_input_enters_configure_mode(self):
        """stdin_input must enter configure mode."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        assert "configure" in content.lower()


class TestNGFWAddRulePlanInterface:
    """Test NGFWAddRulePlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWAddRulePlan should have steps attribute."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWAddRulePlan should have verify_step attribute."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWAddRulePlan should have get_context method."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)

    def test_has_name_attribute(self):
        """NGFWAddRulePlan should have name attribute."""
        from plans.ngfw_add_rule import NGFWAddRulePlan

        plan = NGFWAddRulePlan()
        assert hasattr(plan, "name")
        assert plan.name == "ngfw_add_rule"
