"""Tests for shared.channels.groups module."""


class TestRangeEventGroup:
    """Tests for range_event_group function."""

    def test_returns_range_group_name(self):
        """Function returns correctly formatted group name."""
        from shared.channels.groups import range_event_group

        result = range_event_group(123)

        assert result == "range_status_123"

    def test_accepts_integer_range_id(self):
        """Function works with integer range_id."""
        from shared.channels.groups import range_event_group

        result = range_event_group(1)

        assert result == "range_status_1"


class TestUserEventGroup:
    """Tests for user_event_group function."""

    def test_returns_user_group_name(self):
        """Function returns correctly formatted group name."""
        from shared.channels.groups import user_event_group

        result = user_event_group(42)

        assert result == "user_42"

    def test_accepts_integer_user_id(self):
        """Function works with integer user_id."""
        from shared.channels.groups import user_event_group

        result = user_event_group(1)

        assert result == "user_1"


class TestChannelNames:
    """Tests for channel name constants."""

    def test_engine_channel_name(self):
        """Engine channel has correct name."""
        from shared.channels.groups import CHANNEL_ENGINE_STATUS

        assert CHANNEL_ENGINE_STATUS == "range.status.engine"

    def test_cms_channel_name(self):
        """CMS channel has correct name."""
        from shared.channels.groups import CHANNEL_CMS_STATUS

        assert CHANNEL_CMS_STATUS == "range.status.cms"
