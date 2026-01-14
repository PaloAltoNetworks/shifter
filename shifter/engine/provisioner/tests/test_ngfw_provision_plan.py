"""Tests for NGFWProvisionPlan.

NGFWProvisionPlan handles post-Pulumi NGFW configuration via SSH:
- Enable cloud logging (Strata Logging Service)
- Create log forwarding profile (XDR-Forward)
- Create security policy (allow-all rule with logging)

Note: SSH wait is handled by main.py before this plan runs.
Serial number polling is also in main.py (after plan completes).
Commands use stdin_input for PAN-OS configure mode.
"""

from dataclasses import dataclass

import pytest


@dataclass
class MockNGFWInstance:
    """Mock NGFW instance for testing get_context."""

    management_ip: str = "10.1.1.50"
    sls_region: str = "us"


class TestNGFWProvisionPlanStructure:
    """Test NGFWProvisionPlan step definitions and verification."""

    def test_plan_structure(self):
        """Plan should have 3 steps with proper attributes."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()

        # Should have 3 steps
        assert len(plan.steps) == 3

        # All steps must have required attributes
        for step in plan.steps:
            assert step.name, "Step must have a name"
            assert step.script or step.stdin_input, f"Step {step.name} must have content"
            assert step.timeout_seconds > 0, f"Step {step.name} must have positive timeout"

        # NGFW verification is handled by poll_for_serial_and_cert() in main.py,
        # not via a verify_step (serial + cert polling happens after plan completes)
        assert plan.verify_step is None

    def test_steps_in_correct_order(self):
        """Steps must be in correct order: logging before profile."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        step_names = [s.name for s in plan.steps]

        # Cloud logging must come before log forwarding profile
        cloud_logging_idx = next(i for i, n in enumerate(step_names) if "cloud_logging" in n)
        profile_idx = next(i for i, n in enumerate(step_names) if "log_forwarding" in n)
        assert cloud_logging_idx < profile_idx


class TestNGFWProvisionPlanContext:
    """Test NGFWProvisionPlan.get_context method."""

    def test_get_context_returns_required_fields(self):
        """get_context should return management_ip and sls_region."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        instance = MockNGFWInstance(management_ip="10.1.1.100", sls_region="americas")
        context = plan.get_context(instance)

        assert context["management_ip"] == "10.1.1.100"
        assert context["sls_region"] == "americas"

    def test_get_context_missing_management_ip_raises(self):
        """get_context should raise if management_ip is missing."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        instance = MockNGFWInstance()
        instance.management_ip = None

        with pytest.raises(ValueError, match="management_ip"):
            plan.get_context(instance)


class TestNGFWProvisionPlanScripts:
    """Test NGFWProvisionPlan script/stdin_input content."""

    def test_cloud_logging_stdin_enables_sls(self):
        """Cloud logging stdin_input should enable Strata Logging Service."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        logging_step = next(s for s in plan.steps if "cloud_logging" in s.name)

        assert "logging-service-forwarding" in logging_step.stdin_input
        assert "enable yes" in logging_step.stdin_input

    def test_log_forwarding_profile_creates_xdr_forward(self):
        """Log forwarding profile step should create XDR-Forward profile."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        profile_step = next(s for s in plan.steps if "log_forwarding" in s.name)

        assert "XDR-Forward" in profile_step.stdin_input
        assert "log-settings" in profile_step.stdin_input

    def test_security_policy_creates_allow_all_rule(self):
        """Security policy step should create allow-all rule with logging."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        policy_step = next(s for s in plan.steps if "security_policy" in s.name)

        content = policy_step.stdin_input
        assert "rulebase security" in content or "security rules" in content
        assert "allow" in content.lower()
        assert "log" in content.lower()

    def test_configure_steps_include_commit(self):
        """Configuration steps using stdin_input must include commit command."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()

        config_steps = [s for s in plan.steps if s.stdin_input]
        for step in config_steps:
            assert "commit" in step.stdin_input.lower(), f"Step {step.name} missing commit"
