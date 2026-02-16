"""Tests for shared.enums module."""


class TestResourceStatus:
    """Tests for ResourceStatus enum."""

    # ---------------------------------------------------------------------
    # Enum values - correct set of statuses
    # ---------------------------------------------------------------------

    def test_has_pending_status(self):
        """ResourceStatus has PENDING value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.PENDING == "pending"

    def test_has_provisioning_status(self):
        """ResourceStatus has PROVISIONING value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.PROVISIONING == "provisioning"

    def test_has_ready_status(self):
        """ResourceStatus has READY value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.READY == "ready"

    def test_has_pausing_status(self):
        """ResourceStatus has PAUSING value."""
        from shared.enums import ResourceStatus

        assert ResourceStatus.PAUSING == "pausing"

    def test_has_paused_status(self):
        """ResourceStatus has PAUSED value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.PAUSED == "paused"

    def test_has_resuming_status(self):
        """ResourceStatus has RESUMING value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.RESUMING == "resuming"

    def test_has_destroying_status(self):
        """ResourceStatus has DESTROYING value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.DESTROYING == "destroying"

    def test_has_destroyed_status(self):
        """ResourceStatus has DESTROYED value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.DESTROYED == "destroyed"

    def test_has_failed_status(self):
        """ResourceStatus has FAILED value."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.FAILED == "failed"

    # ---------------------------------------------------------------------
    # String behavior - enum is str subclass
    # ---------------------------------------------------------------------

    def test_is_string_enum(self):
        """ResourceStatus values are strings for JSON serialization."""
        from cyberscript.enums import ResourceStatus

        assert isinstance(ResourceStatus.PENDING, str)
        # Value is the string "pending", direct comparison works
        assert ResourceStatus.PENDING.value == "pending"

    def test_string_comparison(self):
        """ResourceStatus can be compared directly with strings."""
        from cyberscript.enums import ResourceStatus

        assert ResourceStatus.READY == "ready"
        assert ResourceStatus.READY == "ready"

    # ---------------------------------------------------------------------
    # Status groupings - lifecycle categories
    # ---------------------------------------------------------------------

    def test_active_statuses_group(self):
        """ACTIVE_STATUSES contains non-terminal states."""
        from cyberscript.enums import ACTIVE_STATUSES, ResourceStatus

        expected = {
            ResourceStatus.PENDING,
            ResourceStatus.PROVISIONING,
            ResourceStatus.READY,
            ResourceStatus.PAUSING,
            ResourceStatus.PAUSED,
            ResourceStatus.RESUMING,
            ResourceStatus.DESTROYING,
        }
        assert expected == ACTIVE_STATUSES

    def test_terminal_statuses_group(self):
        """TERMINAL_STATUSES contains end states."""
        from cyberscript.enums import TERMINAL_STATUSES, ResourceStatus

        expected = {
            ResourceStatus.DESTROYED,
            ResourceStatus.FAILED,
        }
        assert expected == TERMINAL_STATUSES

    def test_cancellable_statuses_group(self):
        """CANCELLABLE_STATUSES contains states that can be cancelled."""
        from cyberscript.enums import CANCELLABLE_STATUSES, ResourceStatus

        expected = {
            ResourceStatus.PENDING,
            ResourceStatus.PROVISIONING,
        }
        assert expected == CANCELLABLE_STATUSES
