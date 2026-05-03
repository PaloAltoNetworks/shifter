"""Tests for CMS handlers."""

import json
from unittest.mock import patch

from shared.enums import ResourceStatus


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

        with patch("cms.handlers.range_events.process_range_event") as mock_range_handler:
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

        with patch("cms.handlers.ngfw_events.process_ngfw_event") as mock_ngfw_handler:
            process_event(message)
            mock_ngfw_handler.assert_called_once_with(message)

    def test_routes_experiment_events_to_experiments_handler(self):
        """Dispatcher routes experiment.* events to cms.experiments.handlers."""
        from cms.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "experiment.run.started",
                    "experiment_id": 7,
                }
            )
        }

        with patch("cms.experiments.handlers.process_event") as mock_exp_handler:
            process_event(message)
            mock_exp_handler.assert_called_once_with(message)

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
            patch("cms.handlers.range_events.process_range_event") as mock_range_handler,
            patch("cms.handlers.ngfw_events.process_ngfw_event") as mock_ngfw_handler,
            patch("cms.experiments.handlers.process_event") as mock_exp_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()
            mock_exp_handler.assert_not_called()

    def test_handles_missing_event_type(self):
        """Dispatcher handles messages without event_type gracefully."""
        from cms.handlers import process_event

        message = {"Message": json.dumps({"range_id": 1})}

        with (
            patch("cms.handlers.range_events.process_range_event") as mock_range_handler,
            patch("cms.handlers.ngfw_events.process_ngfw_event") as mock_ngfw_handler,
            patch("cms.experiments.handlers.process_event") as mock_exp_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()
            mock_exp_handler.assert_not_called()

    def test_dispatcher_is_callable(self):
        """Dispatcher is a callable function."""
        from cms.handlers import process_event

        assert callable(process_event)


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


class TestProcessRangeEvent:
    """Tests for process_range_event handler."""

    # ---------------------------------------------------------------------
    # Happy path - status update
    # ---------------------------------------------------------------------

    def test_updates_range_instance_status(self):
        """Handler updates RangeInstance.status from event."""
        from unittest.mock import MagicMock

        from cms.handlers import process_range_event

        mock_instance = MagicMock()
        mock_instance.range_id = 1
        mock_instance.user_id = 42
        mock_instance.status = ResourceStatus.PENDING.value
        mock_instance.pk = 1

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

        with (
            patch("cms.handlers.range_events.RangeInstance") as MockRI,
            patch("cms.handlers.range_events.notify_ctf_range_status"),
        ):
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            MockRI.objects.get.assert_called_once_with(range_id=1)
            assert mock_instance.status == ResourceStatus.PROVISIONING.value
            mock_instance.save.assert_called_once_with(update_fields=["status"])

    def test_handles_ready_status(self):
        """Handler correctly handles READY status."""
        from unittest.mock import MagicMock

        from cms.handlers import process_range_event

        mock_instance = MagicMock()
        mock_instance.range_id = 2
        mock_instance.user_id = 42
        mock_instance.status = ResourceStatus.PROVISIONING.value
        mock_instance.pk = 2

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

        with (
            patch("cms.handlers.range_events.RangeInstance") as MockRI,
            patch("cms.handlers.range_events.notify_ctf_range_status"),
            patch("cms.handlers.range_events.notify_experiment_on_range_ready"),
        ):
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            assert mock_instance.status == ResourceStatus.READY.value
            mock_instance.save.assert_called_once_with(update_fields=["status"])

    def test_handles_terminal_status_sets_deleted_at(self):
        """Handler sets deleted_at when status is terminal (DESTROYED).

        Note: deleted_at is set by EntityBase.save() in the model layer.
        We verify the handler calls save() with the correct status; the
        model's save() behaviour is tested elsewhere.
        """
        from unittest.mock import MagicMock

        from cms.handlers import process_range_event

        mock_instance = MagicMock()
        mock_instance.range_id = 3
        mock_instance.user_id = 42
        mock_instance.status = ResourceStatus.DESTROYING.value
        mock_instance.pk = 3

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

        with (
            patch("cms.handlers.range_events.RangeInstance") as MockRI,
            patch("cms.handlers.range_events.notify_ctf_range_status"),
        ):
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            assert mock_instance.status == ResourceStatus.DESTROYED.value
            mock_instance.save.assert_called_once_with(update_fields=["status"])

    # ---------------------------------------------------------------------
    # Event filtering
    # ---------------------------------------------------------------------

    def test_ignores_non_status_events(self):
        """Handler ignores events that are not range.status.updated."""
        from cms.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": 4,
                    "user_id": 42,
                }
            )
        }

        with patch("cms.handlers.range_events.RangeInstance") as MockRI:
            process_range_event(message)

            # Should return early without any DB lookup
            MockRI.objects.get.assert_not_called()

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

        with patch("cms.handlers.range_events.RangeInstance") as MockRI:
            MockRI.DoesNotExist = Exception
            MockRI.objects.get.side_effect = MockRI.DoesNotExist("not found")

            # Should not raise - handler returns early
            process_range_event(message)

    def test_handles_user_id_mismatch(self):
        """Handler rejects events when user_id doesn't match instance."""
        from unittest.mock import MagicMock

        from cms.handlers import process_range_event

        mock_instance = MagicMock()
        mock_instance.range_id = 5
        mock_instance.user_id = 42
        mock_instance.status = ResourceStatus.PENDING.value

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

        with patch("cms.handlers.range_events.RangeInstance") as MockRI:
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            # Status should be unchanged - save should NOT be called
            assert mock_instance.status == ResourceStatus.PENDING.value
            mock_instance.save.assert_not_called()

    def test_rejects_invalid_status_value(self):
        """Handler rejects events with invalid status values."""
        from cms.handlers import process_range_event

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

        with patch("cms.handlers.range_events.RangeInstance") as MockRI:
            # Should return early before any DB lookup
            process_range_event(message)

            MockRI.objects.get.assert_not_called()

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
        from unittest.mock import MagicMock

        from cms.handlers import process_range_event

        mock_instance = MagicMock()
        mock_instance.range_id = 8
        mock_instance.user_id = 42
        mock_instance.status = ResourceStatus.PENDING.value
        mock_instance.pk = 8

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

        with (
            patch("cms.handlers.range_events.RangeInstance") as MockRI,
            patch("cms.handlers.range_events.notify_ctf_range_status"),
        ):
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            assert mock_instance.status == ResourceStatus.PROVISIONING.value
            mock_instance.save.assert_called_once_with(update_fields=["status"])

    # ---------------------------------------------------------------------
    # request_id lookup (new pattern - range_id=None)
    # ---------------------------------------------------------------------

    def test_lookup_by_request_id_when_range_id_is_none(self):
        """Handler finds RangeInstance via request_id when range_id is None.

        This is the new pattern where RangeInstance.range_id is None and
        correlation happens via Request.request_id (UUID).
        """
        from unittest.mock import MagicMock
        from uuid import uuid4

        from cms.handlers import process_range_event

        request_uuid = uuid4()
        user_id = 42

        mock_instance = MagicMock()
        mock_instance.range_id = None  # New pattern: no legacy range_id
        mock_instance.user_id = user_id
        mock_instance.status = ResourceStatus.PENDING.value
        mock_instance.pk = 10

        # Event with request_id (UUID) - the way Engine publishes events
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_uuid),
                    "range_id": 57,  # Engine Range.id (not used for lookup in new pattern)
                    "new_status": ResourceStatus.FAILED.value,
                    "user_id": user_id,
                }
            )
        }

        with (
            patch("cms.handlers.range_events.RangeInstance") as MockRI,
            patch("cms.handlers.range_events.notify_ctf_range_status"),
        ):
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            # Verify lookup was by request_id
            MockRI.objects.get.assert_called_once_with(request__request_id=str(request_uuid))
            assert mock_instance.status == ResourceStatus.FAILED.value
            # range_id from event should be persisted (was None, now set)
            assert mock_instance.range_id == 57
            mock_instance.save.assert_called_once_with(update_fields=["status", "range_id"])

    def test_range_id_not_overwritten_if_already_set(self):
        """Handler does not overwrite an existing range_id with a different value from the event."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        from cms.handlers import process_range_event

        request_uuid = uuid4()
        user_id = 42

        mock_instance = MagicMock()
        mock_instance.range_id = 10  # Already has a range_id
        mock_instance.user_id = user_id
        mock_instance.status = ResourceStatus.PENDING.value
        mock_instance.pk = 11

        # Event carries a different range_id
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_uuid),
                    "range_id": 99,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user_id,
                }
            )
        }

        with (
            patch("cms.handlers.range_events.RangeInstance") as MockRI,
            patch("cms.handlers.range_events.notify_ctf_range_status"),
        ):
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            assert mock_instance.status == ResourceStatus.PROVISIONING.value
            # Original range_id preserved, not overwritten
            assert mock_instance.range_id == 10
            # save should only update status (not range_id)
            mock_instance.save.assert_called_once_with(update_fields=["status"])

    def test_request_id_lookup_preferred_over_range_id(self):
        """Handler prefers request_id lookup over range_id when both present.

        Ensures events with both identifiers use request_id for lookup,
        maintaining proper service layer boundaries.
        """
        from unittest.mock import MagicMock
        from uuid import uuid4

        from cms.handlers import process_range_event

        request_uuid = uuid4()
        user_id = 42

        mock_instance = MagicMock()
        mock_instance.range_id = 100
        mock_instance.user_id = user_id
        mock_instance.status = ResourceStatus.PENDING.value
        mock_instance.pk = 12

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_uuid),
                    "range_id": 100,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": user_id,
                }
            )
        }

        with (
            patch("cms.handlers.range_events.RangeInstance") as MockRI,
            patch("cms.handlers.range_events.notify_ctf_range_status"),
            patch("cms.handlers.range_events.notify_experiment_on_range_ready"),
        ):
            MockRI.objects.get.return_value = mock_instance
            MockRI.DoesNotExist = Exception

            process_range_event(message)

            # Verify lookup was by request_id, NOT range_id
            MockRI.objects.get.assert_called_once_with(request__request_id=str(request_uuid))
            assert mock_instance.status == ResourceStatus.READY.value
