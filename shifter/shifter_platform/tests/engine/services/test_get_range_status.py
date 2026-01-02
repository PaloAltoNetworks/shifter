"""Tests for get_range_status() in engine/services.py."""

import logging
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest


@pytest.mark.django_db
class TestGetRangeStatus:
    """Tests for get_range_status() in engine/services.py.

    Tests the service contract:
    - Inputs: range_id (required int)
    - Outputs: dict with status info or None if not found
    - Side effects: none (read-only)
    - Errors: none raised (returns None for not found)
    - Logging: DEBUG on entry, WARNING if not found
    """

    # -------------------------------------------------------------------------
    # Outputs - returns dict with status info
    # -------------------------------------------------------------------------

    def test_returns_dict_with_status(self):
        """Service returns dict containing status field."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=[],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)

            assert result is not None
            assert result["status"] == Range.Status.READY

    def test_returns_error_message(self):
        """Service returns error_message field."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.FAILED,
            error_message="Provisioning failed: subnet exhausted",
            provisioned_instances=[],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=None,
        )

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)

            assert result["error_message"] == "Provisioning failed: subnet exhausted"

    def test_returns_instances(self):
        """Service returns provisioned_instances as instances field."""
        from engine.models import Range
        from engine.services import get_range_status

        instances = [
            {"uuid": "abc-123", "role": "attacker", "private_ip": "10.1.1.10"},
            {"uuid": "def-456", "role": "victim", "private_ip": "10.1.1.20"},
        ]
        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=instances,
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)

            assert result["instances"] == instances

    def test_returns_empty_list_when_no_instances(self):
        """Service returns empty list when provisioned_instances is None."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.PROVISIONING,
            error_message="",
            provisioned_instances=None,
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=None,
        )

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)

            assert result["instances"] == []

    def test_returns_timestamps_as_iso_strings(self):
        """Service returns timestamps as ISO format strings."""
        from engine.models import Range
        from engine.services import get_range_status

        created = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        ready = datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC)
        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=[],
            created_at=created,
            ready_at=ready,
        )

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)

            assert result["created_at"] == created.isoformat()
            assert result["ready_at"] == ready.isoformat()

    def test_returns_none_for_null_timestamps(self):
        """Service returns None for timestamps that are not set."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.PROVISIONING,
            error_message="",
            provisioned_instances=[],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=None,
        )

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)

            assert result["ready_at"] is None

    def test_returns_none_when_range_not_found(self):
        """Service returns None when range doesn't exist."""
        from engine.models import Range
        from engine.services import get_range_status

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist):
            result = get_range_status(999)
            assert result is None

    # -------------------------------------------------------------------------
    # Side effects - none (read-only)
    # -------------------------------------------------------------------------

    def test_does_not_modify_range(self):
        """Service does not modify the Range object."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=[],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

        with patch.object(Range.objects, "get", return_value=mock_range):
            get_range_status(42)

            mock_range.save.assert_not_called()

    # -------------------------------------------------------------------------
    # Logging - DEBUG on entry
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=[],
            created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            ready_at=datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC),
        )

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            get_range_status(42)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - WARNING when not found
    # -------------------------------------------------------------------------

    def test_logs_warning_when_not_found(self, caplog):
        """Service logs warning when range not found."""
        from engine.models import Range
        from engine.services import get_range_status

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            get_range_status(999)

        assert "not found" in caplog.text.lower() or "999" in caplog.text
