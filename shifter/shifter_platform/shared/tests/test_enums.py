"""Tests for shared.enums module."""


class TestRangeStatus:
    """Tests for RangeStatus enum."""

    # ---------------------------------------------------------------------
    # Enum values - correct set of statuses
    # ---------------------------------------------------------------------

    def test_has_pending_status(self):
        """RangeStatus has PENDING value."""
        from shared.enums import RangeStatus

        assert RangeStatus.PENDING == "pending"

    def test_has_provisioning_status(self):
        """RangeStatus has PROVISIONING value."""
        from shared.enums import RangeStatus

        assert RangeStatus.PROVISIONING == "provisioning"

    def test_has_ready_status(self):
        """RangeStatus has READY value."""
        from shared.enums import RangeStatus

        assert RangeStatus.READY == "ready"

    def test_has_paused_status(self):
        """RangeStatus has PAUSED value."""
        from shared.enums import RangeStatus

        assert RangeStatus.PAUSED == "paused"

    def test_has_resuming_status(self):
        """RangeStatus has RESUMING value."""
        from shared.enums import RangeStatus

        assert RangeStatus.RESUMING == "resuming"

    def test_has_destroying_status(self):
        """RangeStatus has DESTROYING value."""
        from shared.enums import RangeStatus

        assert RangeStatus.DESTROYING == "destroying"

    def test_has_destroyed_status(self):
        """RangeStatus has DESTROYED value."""
        from shared.enums import RangeStatus

        assert RangeStatus.DESTROYED == "destroyed"

    def test_has_failed_status(self):
        """RangeStatus has FAILED value."""
        from shared.enums import RangeStatus

        assert RangeStatus.FAILED == "failed"

    # ---------------------------------------------------------------------
    # String behavior - enum is str subclass
    # ---------------------------------------------------------------------

    def test_is_string_enum(self):
        """RangeStatus values are strings for JSON serialization."""
        from shared.enums import RangeStatus

        assert isinstance(RangeStatus.PENDING, str)
        # Value is the string "pending", direct comparison works
        assert RangeStatus.PENDING.value == "pending"

    def test_string_comparison(self):
        """RangeStatus can be compared directly with strings."""
        from shared.enums import RangeStatus

        assert RangeStatus.READY == "ready"
        assert RangeStatus.READY == "ready"

    # ---------------------------------------------------------------------
    # Status groupings - lifecycle categories
    # ---------------------------------------------------------------------

    def test_active_statuses_group(self):
        """ACTIVE_STATUSES contains non-terminal states."""
        from shared.enums import ACTIVE_STATUSES, RangeStatus

        expected = {
            RangeStatus.PENDING,
            RangeStatus.PROVISIONING,
            RangeStatus.READY,
            RangeStatus.PAUSED,
            RangeStatus.RESUMING,
            RangeStatus.DESTROYING,
        }
        assert expected == ACTIVE_STATUSES

    def test_terminal_statuses_group(self):
        """TERMINAL_STATUSES contains end states."""
        from shared.enums import TERMINAL_STATUSES, RangeStatus

        expected = {
            RangeStatus.DESTROYED,
            RangeStatus.FAILED,
        }
        assert expected == TERMINAL_STATUSES

    def test_cancellable_statuses_group(self):
        """CANCELLABLE_STATUSES contains states that can be cancelled."""
        from shared.enums import CANCELLABLE_STATUSES, RangeStatus

        expected = {
            RangeStatus.PENDING,
            RangeStatus.PROVISIONING,
        }
        assert expected == CANCELLABLE_STATUSES
