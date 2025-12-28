"""Tests for LinuxXDRAgentInstallPlan - only meaningful tests."""

from dataclasses import dataclass
from typing import Optional

import pytest

from components.plans.linux_xdr_agent_install import LinuxXDRAgentInstallPlan


@dataclass
class MockLinuxInstance:
    agent_presigned_url: Optional[str] = None


class TestLinuxXDRAgentInstallPlanContext:
    """Test context generation and validation."""

    def test_get_context_returns_presigned_url(self):
        """get_context returns agent_presigned_url."""
        plan = LinuxXDRAgentInstallPlan()
        instance = MockLinuxInstance(agent_presigned_url="https://example.com/agent.sh")
        context = plan.get_context(instance)
        assert context["agent_presigned_url"] == "https://example.com/agent.sh"

    def test_get_context_missing_url_raises(self):
        """get_context raises ValueError if URL is missing."""
        plan = LinuxXDRAgentInstallPlan()
        instance = MockLinuxInstance(agent_presigned_url=None)
        with pytest.raises(ValueError, match="agent_presigned_url"):
            plan.get_context(instance)

    def test_get_context_empty_url_raises(self):
        """get_context raises ValueError if URL is empty."""
        plan = LinuxXDRAgentInstallPlan()
        instance = MockLinuxInstance(agent_presigned_url="")
        with pytest.raises(ValueError, match="agent_presigned_url"):
            plan.get_context(instance)
