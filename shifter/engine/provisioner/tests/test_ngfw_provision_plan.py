"""Tests for NGFWProvisionPlan.

NGFWProvisionPlan handles post-Pulumi NGFW configuration via SSH:
- Configure data interface (ethernet1/1 as L3 DHCP + virtual router)
- Create shared 'ranges' zone for all range traffic
- Delete default allow-all rule (bypasses per-range logging)
- Enable cloud logging (Strata Logging Service)
- Create log forwarding profile (XDR-Forward)

Note: No default security policy is created. Per-range rules are
created by NGFWConfigureSubnetsPlan during range provisioning.

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
        """Plan should have 5 steps with proper attributes."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()

        # Should have 5 steps (interface + zone + delete allow-all + logging + profile)
        assert len(plan.steps) == 5

        # All steps must have required attributes
        for step in plan.steps:
            assert step.name, "Step must have a name"
            assert step.script or step.stdin_input, f"Step {step.name} must have content"
            assert step.timeout_seconds > 0, f"Step {step.name} must have positive timeout"

        # NGFW verification is handled by poll_for_serial_and_cert() in main.py,
        # not via a verify_step (serial + cert polling happens after plan completes)
        assert plan.verify_step is None

    def test_steps_in_correct_order(self):
        """Steps must be in correct order: interface, zone, delete allow-all, logging, profile."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        step_names = [s.name for s in plan.steps]

        # Interface config must come first
        interface_idx = next(i for i, n in enumerate(step_names) if "data_interface" in n)
        assert interface_idx == 0

        # Zone creation must come after interface config
        zone_idx = next(i for i, n in enumerate(step_names) if "zone" in n)
        assert zone_idx > interface_idx

        # Delete allow-all must come after zone creation
        delete_allow_all_idx = next(i for i, n in enumerate(step_names) if "allow_all" in n)
        assert delete_allow_all_idx > zone_idx

        # Cloud logging must come after delete allow-all
        cloud_logging_idx = next(i for i, n in enumerate(step_names) if "cloud_logging" in n)
        assert cloud_logging_idx > delete_allow_all_idx

        # Log forwarding profile must come last
        profile_idx = next(i for i, n in enumerate(step_names) if "log_forwarding" in n)
        assert profile_idx > cloud_logging_idx


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

    def test_shared_zone_creates_ranges_zone(self):
        """Shared zone step should create 'ranges' zone with ethernet1/1."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        zone_step = next(s for s in plan.steps if "zone" in s.name)

        assert "zone ranges" in zone_step.stdin_input
        assert "ethernet1/1" in zone_step.stdin_input

    def test_data_interface_includes_virtual_router(self):
        """Data interface step should assign ethernet1/1 to virtual router."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        interface_step = next(s for s in plan.steps if "data_interface" in s.name)

        assert "virtual-router default" in interface_step.stdin_input
        assert "ethernet1/1" in interface_step.stdin_input

    def test_delete_allow_all_rule_removes_default_rule(self):
        """Delete allow-all step should remove the default allow-all rule."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()
        delete_step = next(s for s in plan.steps if "allow_all" in s.name)

        assert "delete rulebase security rules allow-all" in delete_step.stdin_input

    def test_configure_steps_include_commit(self):
        """Configuration steps using stdin_input must include commit command."""
        from plans.ngfw_provision import NGFWProvisionPlan

        plan = NGFWProvisionPlan()

        config_steps = [s for s in plan.steps if s.stdin_input]
        for step in config_steps:
            assert "commit" in step.stdin_input.lower(), f"Step {step.name} missing commit"
