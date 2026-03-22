"""Tests for DomainJoinPlan.

DomainJoinPlan defines the steps to join a Windows machine to an AD domain.
"""

import pytest

from plans.domain_join import DomainJoinPlan


class TestDomainJoinPlanSteps:
    """Tests for domain join plan step definitions."""

    def test_steps_in_correct_order(self):
        """DNS must be set before domain join."""
        plan = DomainJoinPlan()
        step_names = [step.name for step in plan.steps]
        assert step_names == ["set_dns", "join_domain"]

    def test_join_domain_requires_reboot(self):
        """Join domain step requires reboot."""
        plan = DomainJoinPlan()
        join_step = next(s for s in plan.steps if s.name == "join_domain")
        assert join_step.requires_reboot is True

    def test_set_dns_does_not_require_reboot(self):
        """Set DNS step does not require reboot."""
        plan = DomainJoinPlan()
        dns_step = next(s for s in plan.steps if s.name == "set_dns")
        assert dns_step.requires_reboot is False


class TestDomainJoinPlanContext:
    """Tests for get_context method."""

    def test_get_context_returns_all_vars(self):
        """get_context returns all required template variables."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": "10.0.0.10",
            "domain_name": "test.local",
            "domain_admin_password": "TestPass123!",  # nosec B105  # NOSONAR — test fixture
        }
        context = plan.get_context(dc_config)

        assert context["dc_ip"] == "10.0.0.10"
        assert context["domain_name"] == "test.local"
        assert context["domain_admin_password"] == "TestPass123!"  # nosec B105  # NOSONAR
        assert context["domain_admin_user"] == "Administrator"

    def test_get_context_custom_admin_user(self):
        """get_context uses custom admin user if provided."""
        plan = DomainJoinPlan()
        dc_config = {
            "dc_ip": "10.0.0.10",
            "domain_name": "test.local",
            "domain_admin_password": "TestPass123!",  # nosec B105  # NOSONAR — test fixture
            "domain_admin_user": "DomainAdmin",
        }
        context = plan.get_context(dc_config)
        assert context["domain_admin_user"] == "DomainAdmin"

    def test_get_context_missing_required_fields_raises(self):
        """Missing required fields raise ValueError."""
        plan = DomainJoinPlan()

        with pytest.raises(ValueError, match="dc_ip"):
            plan.get_context({"domain_name": "test.local", "domain_admin_password": "x"})

        with pytest.raises(ValueError, match="domain_name"):
            plan.get_context({"dc_ip": "10.0.0.10", "domain_admin_password": "x"})

        with pytest.raises(ValueError, match="domain_admin_password"):
            plan.get_context({"dc_ip": "10.0.0.10", "domain_name": "test.local"})


class TestDomainJoinPlanScripts:
    """Tests for script content."""

    def test_dns_script_uses_correct_cmdlet(self):
        """Set DNS script uses Set-DnsClientServerAddress."""
        plan = DomainJoinPlan()
        dns_step = next(s for s in plan.steps if s.name == "set_dns")
        assert "Set-DnsClientServerAddress" in dns_step.script
        assert "{{ dc_ip }}" in dns_step.script or "{{dc_ip}}" in dns_step.script

    def test_join_script_uses_correct_cmdlet(self):
        """Join domain script uses Add-Computer."""
        plan = DomainJoinPlan()
        join_step = next(s for s in plan.steps if s.name == "join_domain")
        assert "Add-Computer" in join_step.script

    def test_password_uses_securestring(self):
        """Password is converted to SecureString."""
        plan = DomainJoinPlan()
        join_step = next(s for s in plan.steps if s.name == "join_domain")
        assert "ConvertTo-SecureString" in join_step.script
