"""Tests for LinuxXDRAgentInstallPlan - only meaningful tests."""

import pytest

from components.plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan


class TestLinuxXDRAgentInstallPlanContext:
    """Test context generation and validation."""

    def test_get_context_returns_presigned_url(self):
        """get_context returns agent_presigned_url."""
        plan = LinuxXDRAgentInstallPlan()
        context = plan.get_context({
            "agent_presigned_url": "https://example.com/agent.sh"
        })
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
