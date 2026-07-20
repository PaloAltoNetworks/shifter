"""Tests for shared.channels.groups module."""

import pytest


class TestRangeEventGroup:
    """Tests for range_event_group function."""

    @pytest.mark.parametrize(
        ("request_id", "expected"),
        [
            (123, "range_status_123"),
            ("abc-123", "range_status_abc-123"),
        ],
    )
    def test_returns_range_group_name(self, request_id, expected):
        """Function returns correctly formatted group names."""
        from cyberscript.channels.groups import range_event_group

        result = range_event_group(request_id)

        assert result == expected


class TestUserEventGroup:
    """Tests for user_event_group function."""

    @pytest.mark.parametrize(
        ("user_id", "expected"),
        [
            (42, "user_42"),
            (1, "user_1"),
        ],
    )
    def test_returns_user_group_name(self, user_id, expected):
        """Function returns correctly formatted group name."""
        from cyberscript.channels.groups import user_event_group

        result = user_event_group(user_id)

        assert result == expected


class TestNotificationTopicGroup:
    """Tests for notification user/topic group names."""

    def test_returns_hashed_user_topic_group(self):
        """Function keeps logical topics out of raw Channels group names."""
        from cyberscript.channels.groups import notification_user_topic_group

        result = notification_user_topic_group(42, "experiment:100")

        assert result.startswith("notify_u42_")
        assert len(result) <= 100
        assert ":" not in result

    def test_same_user_topic_is_stable(self):
        """Function is deterministic for the same user and topic."""
        from cyberscript.channels.groups import notification_user_topic_group

        first = notification_user_topic_group(42, "experiment:100")
        second = notification_user_topic_group(42, "experiment:100")

        assert first == second

    def test_different_topics_do_not_collide(self):
        """Different logical topics produce different group names."""
        from cyberscript.channels.groups import notification_user_topic_group

        assert notification_user_topic_group(42, "experiment:100") != notification_user_topic_group(
            42,
            "experiment:101",
        )
