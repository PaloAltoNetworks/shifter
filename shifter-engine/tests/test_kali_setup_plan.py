"""Tests for KaliSetupPlan - only meaningful tests."""

from dataclasses import dataclass
from typing import Optional

import pytest

from components.plans.kali_setup import KaliSetupPlan


@dataclass
class MockKaliInstance:
    hostname: Optional[str] = None
    public_key: str = ""


class TestKaliSetupPlanContext:
    """Test context generation and validation."""

    def test_get_context_returns_required_fields(self):
        """get_context returns hostname and public_key."""
        plan = KaliSetupPlan()
        instance = MockKaliInstance(hostname="shifter-kali-1", public_key="ssh-ed25519 AAAA...")
        context = plan.get_context(instance)
        assert context["hostname"] == "shifter-kali-1"
        assert context["public_key"] == "ssh-ed25519 AAAA..."

    def test_get_context_missing_hostname_raises(self):
        """get_context raises ValueError if hostname is missing."""
        plan = KaliSetupPlan()
        instance = MockKaliInstance(hostname=None)
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_empty_hostname_raises(self):
        """get_context raises ValueError if hostname is empty."""
        plan = KaliSetupPlan()
        instance = MockKaliInstance(hostname="")
        with pytest.raises(ValueError, match="hostname"):
            plan.get_context(instance)

    def test_get_context_empty_public_key_allowed(self):
        """Empty public_key is allowed (SSH setup skipped)."""
        plan = KaliSetupPlan()
        instance = MockKaliInstance(hostname="shifter-kali-1", public_key="")
        context = plan.get_context(instance)
        assert context["public_key"] == ""
