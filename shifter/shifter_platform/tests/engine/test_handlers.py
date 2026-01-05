"""Tests for Engine handlers."""

import json
import logging
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from shared.enums import RangeStatus

User = get_user_model()


@pytest.mark.django_db
class TestParseSnsMessage:
    """Tests for parse_sns_message helper."""

    def test_parses_sns_wrapped_message(self):
        """Function unwraps SNS envelope to get event payload."""
        from engine.handlers import parse_sns_message

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
        from engine.handlers import parse_sns_message

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
        from engine.handlers import parse_sns_message

        direct_message = {
            "event_type": "range.status.updated",
            "range_id": 1,
            "user_id": 42,
        }

        result = parse_sns_message(direct_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1


@pytest.fixture
def user():
    """Create a test user."""
    return User.objects.create_user(username="testuser", password="testpass")


@pytest.mark.django_db
class TestProcessRangeEvent:
    """Tests for process_range_event handler."""

    # ---------------------------------------------------------------------
    # Happy path - status update
    # ---------------------------------------------------------------------

    def test_updates_range_status(self, user):
        """Handler updates Range.status from event."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.PROVISIONING.value

    def test_sets_ready_at_on_ready_status(self, user):
        """Handler sets ready_at when transitioning to READY."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PROVISIONING.value,
        )
        assert range_obj.ready_at is None

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.READY.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.READY.value
        assert range_obj.ready_at is not None

    def test_sets_destroyed_at_on_destroyed_status(self, user):
        """Handler sets destroyed_at when transitioning to DESTROYED."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.DESTROYING.value,
        )
        assert range_obj.destroyed_at is None

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.DESTROYED.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.DESTROYED.value
        assert range_obj.destroyed_at is not None

    def test_stores_error_message_on_failed_status(self, user):
        """Handler stores error_message when transitioning to FAILED."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PROVISIONING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.FAILED.value,
                    "user_id": user.id,
                    "error_message": "Subnet exhausted",
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.FAILED.value
        assert range_obj.error_message == "Subnet exhausted"

    # ---------------------------------------------------------------------
    # Event filtering
    # ---------------------------------------------------------------------

    def test_ignores_non_status_events(self, user, caplog):
        """Handler ignores events that are not range.status.updated."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": range_obj.id,
                    "user_id": user.id,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="engine.handlers"):
            process_range_event(message)

        assert "Ignoring event_type" in caplog.text

        # Status should be unchanged
        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Error handling - missing data
    # ---------------------------------------------------------------------

    def test_handles_missing_range(self, caplog):
        """Handler logs warning when Range not found."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 999999,
                    "new_status": RangeStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.WARNING, logger="engine.handlers"):
            process_range_event(message)

        assert "Range not found" in caplog.text
        assert "999999" in caplog.text

    def test_handles_user_id_mismatch(self, user, caplog):
        """Handler logs error when user_id doesn't match Range."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.READY.value,
                    "user_id": 999999,  # Wrong user
                }
            )
        }

        with caplog.at_level(logging.ERROR, logger="engine.handlers"):
            process_range_event(message)

        assert "user_id mismatch" in caplog.text
        assert "999999" in caplog.text

        # Status should be unchanged
        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_logs_exception_on_database_error(self, user, caplog):
        """Handler logs exception when database save fails."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        with (
            caplog.at_level(logging.ERROR, logger="engine.handlers"),
            patch.object(Range, "save", side_effect=Exception("DB down")),
        ):
            process_range_event(message)

        assert "DB error saving Range" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text

    # ---------------------------------------------------------------------
    # Logging - success
    # ---------------------------------------------------------------------

    def test_logs_info_on_successful_update(self, user, caplog):
        """Handler logs INFO when status successfully updated."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        with caplog.at_level(logging.INFO, logger="engine.handlers"):
            process_range_event(message)

        assert "Engine updated Range" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text
        assert "pending" in caplog.text
        assert "provisioning" in caplog.text

    def test_logs_debug_on_event_ignore(self, caplog):
        """Handler logs DEBUG when ignoring non-status events."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.destroyed",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="engine.handlers"):
            process_range_event(message)

        assert "Ignoring event_type" in caplog.text
        assert "range.destroyed" in caplog.text

    # ---------------------------------------------------------------------
    # Handler is callable
    # ---------------------------------------------------------------------

    def test_handler_is_callable(self):
        """Handler is a callable function."""
        from engine.handlers import process_range_event

        assert callable(process_range_event)

    # ---------------------------------------------------------------------
    # Minimum required input
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self, user):
        """Handler works with minimal event fields."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PENDING.value,
        )

        # Minimal SNS message - no error_message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.PROVISIONING.value

    def test_failed_without_error_message(self, user):
        """Handler handles FAILED status even without error_message."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=RangeStatus.PROVISIONING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.FAILED.value,
                    "user_id": user.id,
                    # No error_message
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == RangeStatus.FAILED.value
        assert range_obj.error_message == ""  # Default empty string
