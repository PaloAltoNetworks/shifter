"""Tests for XDR Agent installation plan."""

import pytest

from plans.xdr_agent_install import XDRAgentInstallPlan


class TestXDRAgentInstallPlanSteps:
    """Tests for XDRAgentInstallPlan step configuration."""

    def test_has_two_steps(self):
        """Plan should have exactly 2 steps: download and install."""
        plan = XDRAgentInstallPlan()
        assert len(plan.steps) == 2

    def test_steps_in_correct_order(self):
        """Steps should be in order: download, install."""
        plan = XDRAgentInstallPlan()
        assert plan.steps[0].name == "download_xdr_agent"
        assert plan.steps[1].name == "install_xdr_agent"

    def test_no_steps_require_reboot(self):
        """XDR install steps should not require reboot."""
        plan = XDRAgentInstallPlan()
        for step in plan.steps:
            assert not step.requires_reboot

    def test_all_steps_have_names(self):
        """All steps should have non-empty names."""
        plan = XDRAgentInstallPlan()
        for step in plan.steps:
            assert step.name
            assert len(step.name) > 0

    def test_all_steps_have_scripts(self):
        """All steps should have non-empty scripts."""
        plan = XDRAgentInstallPlan()
        for step in plan.steps:
            assert step.script
            assert len(step.script) > 0

    def test_all_steps_have_timeouts(self):
        """All steps should have reasonable timeouts."""
        plan = XDRAgentInstallPlan()
        for step in plan.steps:
            assert step.timeout_seconds > 0
            assert step.timeout_seconds <= 1200  # Max 20 min


class TestXDRAgentInstallPlanVerification:
    """Tests for XDRAgentInstallPlan verification step."""

    def test_has_verification_step(self):
        """Plan should have a verification step."""
        plan = XDRAgentInstallPlan()
        assert plan.verify_step is not None

    def test_verification_step_name(self):
        """Verification step should be named verify_xdr_agent."""
        plan = XDRAgentInstallPlan()
        assert plan.verify_step.name == "verify_xdr_agent"

    def test_verification_step_is_marked_as_verification(self):
        """Verification step should have is_verification=True."""
        plan = XDRAgentInstallPlan()
        assert plan.verify_step.is_verification is True

    def test_verification_step_has_script(self):
        """Verification step should have a script."""
        plan = XDRAgentInstallPlan()
        assert plan.verify_step.script
        assert len(plan.verify_step.script) > 0


class TestXDRAgentInstallPlanContext:
    """Tests for XDRAgentInstallPlan context generation."""

    def test_get_context_returns_presigned_url(self):
        """get_context should return agent_presigned_url."""
        plan = XDRAgentInstallPlan()
        context = plan.get_context({
            "agent_presigned_url": "https://example.com/agent.msi"
        })
        assert "agent_presigned_url" in context
        assert context["agent_presigned_url"] == "https://example.com/agent.msi"

    def test_get_context_missing_url_raises(self):
        """get_context should raise ValueError if URL is missing."""
        plan = XDRAgentInstallPlan()
        with pytest.raises(ValueError, match="agent_presigned_url"):
            plan.get_context({})

    def test_get_context_empty_url_raises(self):
        """get_context should raise ValueError if URL is empty."""
        plan = XDRAgentInstallPlan()
        with pytest.raises(ValueError, match="agent_presigned_url"):
            plan.get_context({"agent_presigned_url": ""})

    def test_get_context_none_url_raises(self):
        """get_context should raise ValueError if URL is None."""
        plan = XDRAgentInstallPlan()
        with pytest.raises(ValueError, match="agent_presigned_url"):
            plan.get_context({"agent_presigned_url": None})


class TestXDRAgentInstallPlanScripts:
    """Tests for XDRAgentInstallPlan script contents."""

    def test_download_script_uses_invoke_webrequest(self):
        """Download script should use Invoke-WebRequest."""
        plan = XDRAgentInstallPlan()
        download_script = plan.steps[0].script
        assert "Invoke-WebRequest" in download_script

    def test_download_script_uses_tls12(self):
        """Download script should set TLS 1.2 for S3."""
        plan = XDRAgentInstallPlan()
        download_script = plan.steps[0].script
        assert "Tls12" in download_script

    def test_download_script_uses_template_variable(self):
        """Download script should use template variable for URL."""
        plan = XDRAgentInstallPlan()
        download_script = plan.steps[0].script
        assert "{{ agent_presigned_url }}" in download_script

    def test_install_script_uses_msiexec(self):
        """Install script should use msiexec."""
        plan = XDRAgentInstallPlan()
        install_script = plan.steps[1].script
        assert "msiexec" in install_script

    def test_install_script_silent_install(self):
        """Install script should use silent install flags."""
        plan = XDRAgentInstallPlan()
        install_script = plan.steps[1].script
        assert "/qn" in install_script

    def test_install_script_no_restart(self):
        """Install script should use norestart flag."""
        plan = XDRAgentInstallPlan()
        install_script = plan.steps[1].script
        assert "/norestart" in install_script

    def test_verify_script_checks_service(self):
        """Verify script should check for XDR service."""
        plan = XDRAgentInstallPlan()
        verify_script = plan.verify_step.script
        assert "Get-Service" in verify_script
        assert "CortexXDR" in verify_script

    def test_verify_script_checks_alternative_service(self):
        """Verify script should check for alternative service name."""
        plan = XDRAgentInstallPlan()
        verify_script = plan.verify_step.script
        assert "cyserver" in verify_script

    def test_scripts_handle_errors(self):
        """All scripts should have error handling."""
        plan = XDRAgentInstallPlan()
        for step in plan.steps:
            assert "$ErrorActionPreference" in step.script
        assert "$ErrorActionPreference" in plan.verify_step.script


class TestXDRAgentInstallPlanInterface:
    """Tests for XDRAgentInstallPlan interface compliance."""

    def test_has_steps_attribute(self):
        """Plan should have steps attribute."""
        plan = XDRAgentInstallPlan()
        assert hasattr(plan, "steps")
        assert isinstance(plan.steps, list)

    def test_has_verify_step_attribute(self):
        """Plan should have verify_step attribute."""
        plan = XDRAgentInstallPlan()
        assert hasattr(plan, "verify_step")

    def test_has_get_context_method(self):
        """Plan should have get_context method."""
        plan = XDRAgentInstallPlan()
        assert hasattr(plan, "get_context")
        assert callable(plan.get_context)
