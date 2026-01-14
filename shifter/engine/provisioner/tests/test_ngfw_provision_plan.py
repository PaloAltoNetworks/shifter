"""Tests for NGFWProvisionPlan - TDD: Write tests first, all must fail initially.

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


class TestNGFWProvisionPlanSteps:
    """Test NGFWProvisionPlan step definitions."""

    def test_has_expected_steps(self):
        """NGFWProvisionPlan should have 3 steps (SSH wait and serial polling in main.py)."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        assert len(plan.steps) == 3

    def test_steps_in_correct_order(self):
        """Steps must be in correct order: logging, profile, policy."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        step_names = [s.name for s in plan.steps]

        # Cloud logging should be first
        assert "cloud_logging" in step_names[0]
        # Cloud logging before profile
        cloud_logging_idx = next(i for i, n in enumerate(step_names) if "cloud_logging" in n)
        profile_idx = next(i for i, n in enumerate(step_names) if "log_forwarding" in n)
        assert cloud_logging_idx < profile_idx

    def test_all_steps_have_names(self):
        """All steps must have names for logging and debugging."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        for step in plan.steps:
            assert step.name, "Step must have a name"

    def test_all_steps_have_script_or_stdin_input(self):
        """All steps must have script or stdin_input content."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        for step in plan.steps:
            has_content = step.script or step.stdin_input
            assert has_content, f"Step {step.name} must have script or stdin_input"

    def test_all_steps_have_timeouts(self):
        """All steps must have positive timeouts."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        for step in plan.steps:
            assert step.timeout_seconds is not None, f"Step {step.name} missing timeout"
            assert step.timeout_seconds > 0, f"Step {step.name} must have positive timeout"


class TestNGFWProvisionPlanVerification:
    """Test NGFWProvisionPlan verification step."""

    def test_has_verification_step(self):
        """NGFWProvisionPlan should have a verification step."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        assert plan.verify_step is not None

    def test_verification_step_is_marked_as_verification(self):
        """Verification step should have is_verification=True."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        assert plan.verify_step.is_verification is True


class TestNGFWProvisionPlanContext:
    """Test NGFWProvisionPlan.get_context method."""

    def test_get_context_returns_management_ip(self):
        """get_context should return management_ip."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        instance = MockNGFWInstance(management_ip="10.1.1.100")
        context = plan.get_context(instance)

        assert "management_ip" in context
        assert context["management_ip"] == "10.1.1.100"

    def test_get_context_returns_sls_region(self):
        """get_context should return sls_region for Strata Logging Service."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        instance = MockNGFWInstance(sls_region="americas")
        context = plan.get_context(instance)

        assert "sls_region" in context
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

        # stdin_input should contain the validated PAN-OS CLI command
        assert "logging-service-forwarding" in logging_step.stdin_input
        assert "enable yes" in logging_step.stdin_input

    def test_log_forwarding_profile_creates_xdr_forward(self):
        """Log forwarding profile step should create XDR-Forward profile."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        profile_step = next(s for s in plan.steps if "log_forwarding" in s.name)

        # stdin_input should create the XDR-Forward profile
        assert "XDR-Forward" in profile_step.stdin_input
        assert "log-settings" in profile_step.stdin_input

    def test_security_policy_creates_allow_all_rule(self):
        """Security policy step should create allow-all rule with logging."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        policy_step = next(s for s in plan.steps if "security_policy" in s.name)

        # stdin_input should create security rule with logging
        content = policy_step.stdin_input
        assert "rulebase security" in content or "security rules" in content
        assert "allow" in content.lower()
        assert "log" in content.lower()

    def test_configure_steps_include_commit(self):
        """Configuration steps using stdin_input must include commit command."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()

        # All steps with stdin_input should have commit
        config_steps = [s for s in plan.steps if s.stdin_input]
        for step in config_steps:
            assert "commit" in step.stdin_input.lower(), f"Step {step.name} missing commit"


class TestNGFWProvisionPlanInterface:
    """Test NGFWProvisionPlan interface compliance."""

    def test_has_steps_attribute(self):
        """NGFWProvisionPlan should have steps attribute."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """NGFWProvisionPlan should have verify_step attribute."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """NGFWProvisionPlan should have get_context method."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
