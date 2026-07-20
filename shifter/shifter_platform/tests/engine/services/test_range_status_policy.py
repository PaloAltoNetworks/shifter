"""Unit tests for the pure range status-classification predicates.

``is_range_usable`` / ``is_range_terminal`` moved off ``engine.models.Range``
into the lifecycle policy layer (#685) and are expressed against the canonical
``shared.enums.ResourceStatus`` vocabulary rather than the model-local
``Range.Status`` duplicate. Pure functions over a status string — no ORM.
"""

from __future__ import annotations

from engine.services._lifecycle import is_range_terminal, is_range_usable
from shared.enums import ResourceStatus


class TestIsRangeUsable:
    def test_ready_is_usable(self):
        assert is_range_usable(ResourceStatus.READY.value) is True

    def test_paused_is_usable(self):
        assert is_range_usable(ResourceStatus.PAUSED.value) is True

    def test_non_usable_statuses(self):
        for status in (
            ResourceStatus.PENDING,
            ResourceStatus.PROVISIONING,
            ResourceStatus.PAUSING,
            ResourceStatus.RESUMING,
            ResourceStatus.DESTROYING,
            ResourceStatus.DESTROYED,
            ResourceStatus.FAILED,
        ):
            assert is_range_usable(status.value) is False


class TestIsRangeTerminal:
    def test_destroyed_is_terminal(self):
        assert is_range_terminal(ResourceStatus.DESTROYED.value) is True

    def test_failed_is_terminal(self):
        assert is_range_terminal(ResourceStatus.FAILED.value) is True

    def test_non_terminal_statuses(self):
        for status in (
            ResourceStatus.PENDING,
            ResourceStatus.PROVISIONING,
            ResourceStatus.READY,
            ResourceStatus.PAUSING,
            ResourceStatus.PAUSED,
            ResourceStatus.RESUMING,
            ResourceStatus.DESTROYING,
        ):
            assert is_range_terminal(status.value) is False
