"""Tests for NGFWAddRulePlan.

NGFWAddRulePlan creates a PAN-OS security rule allowing traffic between
address objects (subnets).
"""

from dataclasses import dataclass

import pytest

from plans.ngfw_add_rule import NGFWAddRulePlan


@dataclass
class MockRuleConfig:
    """Mock config for testing get_context."""

    rule_name: str = "dc-to-servers"
    src_address: str = "dc-subnet"
    dst_address: str = "servers-subnet"
    management_ip: str = "10.0.4.10"


class TestNGFWAddRulePlan:
    """Tests for NGFWAddRulePlan behavior."""

    def test_step_structure(self):
        """Plan has add_rule step with stdin_input."""
        plan = NGFWAddRulePlan()
        assert len(plan.steps) == 1
        assert plan.steps[0].name == "add_rule"
        assert plan.steps[0].stdin_input, "Step must have stdin_input for PAN-OS"

    def test_get_context_returns_all_fields(self):
        """get_context returns all required fields."""
        plan = NGFWAddRulePlan()
        config = MockRuleConfig(
            rule_name="servers-to-workstations",
            src_address="src-subnet",
            dst_address="dst-subnet",
            management_ip="10.0.4.50",
        )
        context = plan.get_context(config)

        assert context["rule_name"] == "servers-to-workstations"
        assert context["src_address"] == "src-subnet"
        assert context["dst_address"] == "dst-subnet"
        assert context["management_ip"] == "10.0.4.50"

    def test_get_context_missing_fields_raises(self):
        """get_context raises ValueError for missing required fields."""
        plan = NGFWAddRulePlan()

        for field in ["rule_name", "src_address", "dst_address", "management_ip"]:
            config = MockRuleConfig()
            setattr(config, field, None)
            with pytest.raises(ValueError, match=field):
                plan.get_context(config)


class TestNGFWAddRulePlanScripts:
    """Tests for script content."""

    def test_stdin_input_has_required_elements(self):
        """stdin_input has security rule config, template vars, and commit."""
        plan = NGFWAddRulePlan()
        content = plan.steps[0].stdin_input

        # Must configure security rule
        assert "rulebase security rules" in content
        assert "configure" in content.lower()
        assert "commit" in content.lower()

        # Must have template variables
        assert "{{ rule_name }}" in content
        assert "{{ src_address }}" in content
        assert "{{ dst_address }}" in content

        # Must set action and logging
        assert "action allow" in content
        assert "log-end yes" in content
