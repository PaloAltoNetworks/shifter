"""Tests to verify KaliSetupPlan has been removed.

KaliSetupPlan was removed because it duplicated LinuxBootstrapPlan.
Kali instances now use LinuxBootstrapPlan with ssh_user="kali".
"""


class TestKaliSetupPlanRemoved:
    """Verify KaliSetupPlan no longer exists."""

    def test_kali_setup_plan_not_in_plans(self):
        """KaliSetupPlan should not exist - use LinuxBootstrapPlan instead."""
        import plans

        assert not hasattr(plans, "KaliSetupPlan")
