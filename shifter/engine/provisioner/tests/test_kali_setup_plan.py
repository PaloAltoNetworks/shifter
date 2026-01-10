"""Tests to verify KaliSetupPlan has been removed.

KaliSetupPlan was removed because it duplicated LinuxBootstrapPlan.
Kali instances now use LinuxBootstrapPlan with ssh_user="kali".
"""

import pytest


class TestKaliSetupPlanRemoved:
    """Verify KaliSetupPlan no longer exists."""

    def test_kali_setup_plan_module_does_not_exist(self):
        """kali_setup module should not exist."""
        # ImportError raised when importing non-existent name from package
        with pytest.raises(ImportError):
            from plans import kali_setup  # noqa: F401

    def test_kali_setup_plan_class_does_not_exist(self):
        """KaliSetupPlan class should not exist in plans."""
        import plans

        assert not hasattr(plans, "KaliSetupPlan")
