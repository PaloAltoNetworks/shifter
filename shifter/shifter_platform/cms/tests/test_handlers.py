"""Tests for CMS handlers."""

import json
import logging

import pytest

from shared.enums import RangeStatus


@pytest.mark.django_db
class TestParseSnsMessage:
    """Tests for parse_sns_message helper."""

    def test_parses_sns_wrapped_message(self):
        """Function unwraps SNS envelope to get event payload."""
        from cms.handlers import parse_sns_message

        sns_message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        result = parse_sns_message(sns_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1
        assert result["user_id"] == 42

    def test_parses_string_input(self):
        """Function parses string JSON input."""
        from cms.handlers import parse_sns_message

        sns_message = json.dumps(
            {
                "Message": json.dumps(
                    {
                        "event_type": "range.status.updated",
                        "range_id": 1,
                    }
                )
            }
        )

        result = parse_sns_message(sns_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1

    def test_handles_non_wrapped_message(self):
        """Function handles direct event payload (no SNS wrapper)."""
        from cms.handlers import parse_sns_message

        direct_message = {
            "event_type": "range.status.updated",
            "range_id": 1,
            "user_id": 42,
        }

        result = parse_sns_message(direct_message)

        # When no "Message" key, should return the body itself
        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1


@pytest.mark.django_db
class TestProcessRangeEvent:
    """Tests for process_range_event handler."""

    # ---------------------------------------------------------------------
    # Happy path - status update
    # ---------------------------------------------------------------------

    def test_updates_range_instance_status(self):
        """Handler updates RangeInstance.status from event."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        # SNS-wrapped message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=1)
        assert instance.status == RangeStatus.PROVISIONING.value

    def test_handles_ready_status(self):
        """Handler correctly handles READY status."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=2,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PROVISIONING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 2,
                    "new_status": RangeStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=2)
        assert instance.status == RangeStatus.READY.value

    def test_handles_terminal_status_sets_deleted_at(self):
        """Handler sets deleted_at when status is terminal (DESTROYED)."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=3,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.DESTROYING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 3,
                    "new_status": RangeStatus.DESTROYED.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=3)
        assert instance.status == RangeStatus.DESTROYED.value
        assert instance.deleted_at is not None

    # ---------------------------------------------------------------------
    # Event filtering
    # ---------------------------------------------------------------------

    def test_ignores_non_status_events(self, caplog):
        """Handler ignores events that are not range.status.updated."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=4,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": 4,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="cms.handlers"):
            process_range_event(message)

        assert "Ignoring event_type" in caplog.text

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=4)
        assert instance.status == RangeStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Error handling - missing data
    # ---------------------------------------------------------------------

    def test_handles_missing_range_instance(self, caplog):
        """Handler logs warning when RangeInstance not found."""
        from cms.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 999,
                    "new_status": RangeStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.WARNING, logger="cms.handlers"):
            process_range_event(message)

        assert "RangeInstance not found" in caplog.text
        assert "999" in caplog.text

    def test_handles_user_id_mismatch(self, caplog):
        """Handler logs error when user_id doesn't match instance."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=5,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 5,
                    "new_status": RangeStatus.READY.value,
                    "user_id": 999,  # Wrong user
                }
            )
        }

        with caplog.at_level(logging.ERROR, logger="cms.handlers"):
            process_range_event(message)

        assert "user_id mismatch" in caplog.text
        assert "999" in caplog.text
        assert "42" in caplog.text

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=5)
        assert instance.status == RangeStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_logs_exception_on_database_error(self, caplog):
        """Handler logs exception when database save fails."""
        from unittest.mock import patch

        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=6,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 6,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        with (
            caplog.at_level(logging.ERROR, logger="cms.handlers"),
            patch.object(RangeInstance, "save", side_effect=Exception("DB down")),
        ):
            process_range_event(message)

        assert "DB error saving RangeInstance" in caplog.text
        assert "range_id=6" in caplog.text

    # ---------------------------------------------------------------------
    # Logging - success
    # ---------------------------------------------------------------------

    def test_logs_info_on_successful_update(self, caplog):
        """Handler logs INFO when status successfully updated."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=7,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 7,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.INFO, logger="cms.handlers"):
            process_range_event(message)

        assert "CMS updated RangeInstance" in caplog.text
        assert "range_id=7" in caplog.text
        assert "pending" in caplog.text
        assert "provisioning" in caplog.text

    def test_logs_debug_on_event_ignore(self, caplog):
        """Handler logs DEBUG when ignoring non-status events."""
        from cms.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.destroyed",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="cms.handlers"):
            process_range_event(message)

        assert "Ignoring event_type" in caplog.text
        assert "range.destroyed" in caplog.text

    # ---------------------------------------------------------------------
    # Handler is callable
    # ---------------------------------------------------------------------

    def test_handler_is_callable(self):
        """Handler is a callable function."""
        from cms.handlers import process_range_event

        assert callable(process_range_event)

    # ---------------------------------------------------------------------
    # Minimum required input
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self):
        """Handler works with minimal event fields."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=8,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        # Minimal SNS message - no error_message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 8,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=8)
        assert instance.status == RangeStatus.PROVISIONING.value
