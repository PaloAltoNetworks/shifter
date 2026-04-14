"""Tests for LinuxXDRAgentInstallPlan - only meaningful tests."""

import pytest

from plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan


class TestLinuxXDRAgentInstallPlanContext:
    """Test context generation and validation."""

    def test_get_context_returns_presigned_url(self):
        """get_context returns agent_presigned_url."""
        plan = LinuxXDRAgentInstallPlan()
        context = plan.get_context({"agent_presigned_url": "https://example.com/agent.sh"})
        assert context["agent_presigned_url"] == "https://example.com/agent.sh"

    def test_get_context_missing_url_raises(self):
        """get_context raises ValueError if URL is missing."""
        plan = LinuxXDRAgentInstallPlan()
        with pytest.raises(ValueError, match="agent_presigned_url"):
            plan.get_context({})

    def test_get_context_empty_url_raises(self):
        """get_context raises ValueError if URL is empty."""
        plan = LinuxXDRAgentInstallPlan()
        with pytest.raises(ValueError, match="agent_presigned_url"):
            plan.get_context({"agent_presigned_url": ""})


class TestLinuxXDRAgentInstallPlanScripts:
    """Tests for script content needed by GCP/AWS download parity."""

    def test_download_script_uses_redirects_and_retries(self):
        """Download step should tolerate signed object URLs and transient failures."""
        plan = LinuxXDRAgentInstallPlan()
        download_script = plan.steps[0].script

        assert "curl -sSfL" in download_script
        assert "max_retries=5" in download_script
        assert 'sleep "$delay"' in download_script

    def test_download_script_uses_template_url(self):
        """Download step should still render the agent URL from context."""
        plan = LinuxXDRAgentInstallPlan()
        assert "{{ agent_presigned_url }}" in plan.steps[0].script
