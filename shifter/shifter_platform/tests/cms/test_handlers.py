"""Tests for CMS handlers."""

import json
from unittest.mock import patch

import pytest

from shared.enums import ResourceStatus


@pytest.mark.django_db
class TestProcessEvent:
    """Tests for process_event dispatcher."""

    def test_routes_range_events_to_range_handler(self):
        """Dispatcher routes range.* events to process_range_event."""
        from cms.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("cms.handlers.process_range_event") as mock_range_handler:
            process_event(message)
            mock_range_handler.assert_called_once_with(message)

    def test_routes_ngfw_events_to_ngfw_handler(self):
        """Dispatcher routes ngfw.* events to process_ngfw_event."""
        from cms.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "ngfw.status.updated",
                    "ngfw_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("cms.handlers.process_ngfw_event") as mock_ngfw_handler:
            process_event(message)
            mock_ngfw_handler.assert_called_once_with(message)

    def test_ignores_unknown_event_types(self):
        """Dispatcher ignores events with unknown event_type prefix."""
        from cms.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "unknown.event",
                    "some_id": 1,
                }
            )
        }

        with (
            patch("cms.handlers.process_range_event") as mock_range_handler,
            patch("cms.handlers.process_ngfw_event") as mock_ngfw_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()

    def test_handles_missing_event_type(self):
        """Dispatcher handles messages without event_type gracefully."""
        from cms.handlers import process_event

        message = {"Message": json.dumps({"range_id": 1})}

        with (
            patch("cms.handlers.process_range_event") as mock_range_handler,
            patch("cms.handlers.process_ngfw_event") as mock_ngfw_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()

    def test_dispatcher_is_callable(self):
        """Dispatcher is a callable function."""
        from cms.handlers import process_event

        assert callable(process_event)


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
            status=ResourceStatus.PENDING.value,
        )

        # SNS-wrapped message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=1)
        assert instance.status == ResourceStatus.PROVISIONING.value

    def test_handles_ready_status(self):
        """Handler correctly handles READY status."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=2,
            scenario_id="basic",
            user_id=42,
            status=ResourceStatus.PROVISIONING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 2,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=2)
        assert instance.status == ResourceStatus.READY.value

    def test_handles_terminal_status_sets_deleted_at(self):
        """Handler sets deleted_at when status is terminal (DESTROYED)."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=3,
            scenario_id="basic",
            user_id=42,
            status=ResourceStatus.DESTROYING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 3,
                    "new_status": ResourceStatus.DESTROYED.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=3)
        assert instance.status == ResourceStatus.DESTROYED.value
        assert instance.deleted_at is not None

    # ---------------------------------------------------------------------
    # Event filtering
    # ---------------------------------------------------------------------

    def test_ignores_non_status_events(self):
        """Handler ignores events that are not range.status.updated."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=4,
            scenario_id="basic",
            user_id=42,
            status=ResourceStatus.PENDING.value,
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

        process_range_event(message)

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=4)
        assert instance.status == ResourceStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Error handling - missing data
    # ---------------------------------------------------------------------

    def test_handles_missing_range_instance(self):
        """Handler handles missing RangeInstance gracefully (no exception)."""
        from cms.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 999,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        # Should not raise - handler returns early
        process_range_event(message)

    def test_handles_user_id_mismatch(self):
        """Handler rejects events when user_id doesn't match instance."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=5,
            scenario_id="basic",
            user_id=42,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 5,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 999,  # Wrong user
                }
            )
        }

        process_range_event(message)

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=5)
        assert instance.status == ResourceStatus.PENDING.value

    def test_rejects_invalid_status_value(self):
        """Handler rejects events with invalid status values."""
        from cms.handlers import process_range_event
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=50,
            scenario_id="basic",
            user_id=42,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 50,
                    "new_status": "bogus_status",
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=50)
        assert instance.status == ResourceStatus.PENDING.value

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
            status=ResourceStatus.PENDING.value,
        )

        # Minimal SNS message - no error_message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 8,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(range_id=8)
        assert instance.status == ResourceStatus.PROVISIONING.value

    # ---------------------------------------------------------------------
    # request_id lookup (new pattern - range_id=None)
    # ---------------------------------------------------------------------

    def test_lookup_by_request_id_when_range_id_is_none(self):
        """Handler finds RangeInstance via request_id when range_id is None.

        This is the new pattern where RangeInstance.range_id is None and
        correlation happens via Request.request_id (UUID).
        """
        from uuid import uuid4

        from django.contrib.auth import get_user_model

        from cms.handlers import process_range_event
        from cms.models import RangeInstance, Request
        from shared.enums import RequestType

        User = get_user_model()
        user = User.objects.create_user(username="testuser42", password="testpass")

        # Create Request with UUID
        request_uuid = uuid4()
        cms_request = Request.objects.create(
            request_id=request_uuid,
            request_type=RequestType.RANGE.value,
            user=user,
        )

        # Create RangeInstance with range_id=None, linked via request FK
        RangeInstance.objects.create(
            range_id=None,  # New pattern: no legacy range_id
            request=cms_request,
            scenario_id="basic",
            user_id=user.id,
            status=ResourceStatus.PENDING.value,
        )

        # Event with request_id (UUID) - the way Engine publishes events
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_uuid),
                    "range_id": 57,  # Engine Range.id (not used for lookup in new pattern)
                    "new_status": ResourceStatus.FAILED.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        # Verify status updated via request_id lookup
        instance = RangeInstance.objects.get(request__request_id=request_uuid)
        assert instance.status == ResourceStatus.FAILED.value

    def test_request_id_lookup_preferred_over_range_id(self):
        """Handler prefers request_id lookup over range_id when both present.

        Ensures events with both identifiers use request_id for lookup,
        maintaining proper service layer boundaries.
        """
        from uuid import uuid4

        from django.contrib.auth import get_user_model

        from cms.handlers import process_range_event
        from cms.models import RangeInstance, Request
        from shared.enums import RequestType

        User = get_user_model()
        user = User.objects.create_user(username="testuser100", password="testpass")

        request_uuid = uuid4()
        cms_request = Request.objects.create(
            request_id=request_uuid,
            request_type=RequestType.RANGE.value,
            user=user,
        )

        # RangeInstance with BOTH range_id and request FK
        RangeInstance.objects.create(
            range_id=100,
            request=cms_request,
            scenario_id="basic",
            user_id=user.id,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_uuid),
                    "range_id": 100,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        instance = RangeInstance.objects.get(request__request_id=request_uuid)
        assert instance.status == ResourceStatus.READY.value
