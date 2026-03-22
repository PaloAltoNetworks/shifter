"""CMS NGFW handler tests.

Tests for process_ngfw_event handler function:
- Handles ngfw.event events (unified NGFW lifecycle events)
- Updates CMS Instance and App status
- Validates required fields (instance_id, app_id)
- Handles missing Instance/App gracefully
- Validates status values
"""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from shared.enums import ResourceStatus
from shared.messages.events import EVENT_TYPE_NGFW


def make_sns_message(event: dict) -> dict:
    """Wrap event in SNS envelope."""
    return {"Message": json.dumps(event)}


@pytest.fixture
def mock_instance():
    """Create a mock CMS Instance."""
    inst = MagicMock()
    inst.id = uuid4()
    inst.status = ResourceStatus.PROVISIONING.value
    return inst


@pytest.fixture
def mock_app():
    """Create a mock CMS App."""
    app = MagicMock()
    app.id = uuid4()
    app.status = ResourceStatus.PROVISIONING.value
    app.data = {}
    return app


class TestProcessNgfwEvent:
    """Tests for process_ngfw_event handler."""

    # -------------------------------------------------------------------------
    # ngfw.event - status updates
    # -------------------------------------------------------------------------

    def test_updates_status_on_ngfw_event(self, mock_instance, mock_app):
        """process_ngfw_event updates Instance and App status."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.READY.value,
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert mock_instance.status == ResourceStatus.READY.value
        mock_instance.save.assert_called_once_with(update_fields=["status"])
        assert mock_app.status == ResourceStatus.READY.value

    def test_updates_to_failed_status(self, mock_instance, mock_app):
        """process_ngfw_event can update to FAILED status."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.FAILED.value,
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert mock_instance.status == ResourceStatus.FAILED.value
        mock_instance.save.assert_called_once_with(update_fields=["status"])
        assert mock_app.status == ResourceStatus.FAILED.value

    def test_updates_to_destroyed_status(self, mock_instance, mock_app):
        """process_ngfw_event can update to DESTROYED status."""
        mock_instance.status = ResourceStatus.DESTROYING.value
        mock_app.status = ResourceStatus.DESTROYING.value

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.DESTROYED.value,
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert mock_instance.status == ResourceStatus.DESTROYED.value
        mock_instance.save.assert_called_once_with(update_fields=["status"])
        assert mock_app.status == ResourceStatus.DESTROYED.value

    def test_event_without_status_does_not_change_status(self, mock_instance, mock_app):
        """process_ngfw_event with no status field leaves status unchanged."""
        original_instance_status = mock_instance.status
        original_app_status = mock_app.status

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            # No status field
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert mock_instance.status == original_instance_status
        mock_instance.save.assert_not_called()
        assert mock_app.status == original_app_status

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_ignores_unknown_event_type(self, mock_instance, mock_app):
        """process_ngfw_event ignores unknown event types."""
        event = {
            "event_type": "ngfw.unknown.event",
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.READY.value,
        }

        with (
            patch("cms.handlers.Instance.objects.get") as mock_get_instance,
            patch("cms.handlers.App.objects.get") as mock_get_app,
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        # Should not have looked up any models
        mock_get_instance.assert_not_called()
        mock_get_app.assert_not_called()

    def test_handles_missing_instance_gracefully(self, mock_instance, mock_app):
        """process_ngfw_event handles missing Instance gracefully."""
        from cms.models import Instance

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(uuid4()),  # Non-existent
            "app_id": str(mock_app.id),
            "status": ResourceStatus.READY.value,
        }

        with (
            patch(
                "cms.handlers.Instance.objects.get",
                side_effect=Instance.DoesNotExist,
            ),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))  # Should not raise

    def test_handles_missing_app_gracefully(self, mock_instance, mock_app):
        """process_ngfw_event handles missing App gracefully."""
        from cms.models import App

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(uuid4()),  # Non-existent
            "status": ResourceStatus.READY.value,
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", side_effect=App.DoesNotExist),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))  # Should not raise

    def test_handles_missing_required_ids(self, mock_instance, mock_app):
        """process_ngfw_event handles events missing instance_id or app_id."""
        with (
            patch("cms.handlers.Instance.objects.get") as mock_get_instance,
            patch("cms.handlers.App.objects.get") as mock_get_app,
        ):
            from cms.handlers import process_ngfw_event

            # Missing instance_id
            event = {
                "event_type": EVENT_TYPE_NGFW,
                "app_id": str(mock_app.id),
                "status": ResourceStatus.READY.value,
            }
            process_ngfw_event(make_sns_message(event))  # Should not raise

            # Missing app_id
            event = {
                "event_type": EVENT_TYPE_NGFW,
                "instance_id": str(mock_instance.id),
                "status": ResourceStatus.READY.value,
            }
            process_ngfw_event(make_sns_message(event))  # Should not raise

        # Neither lookup should have been attempted
        mock_get_instance.assert_not_called()
        mock_get_app.assert_not_called()

    def test_rejects_invalid_status(self, mock_instance, mock_app):
        """process_ngfw_event rejects invalid status values."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": "invalid_status",
        }

        with (
            patch("cms.handlers.Instance.objects.get") as mock_get_instance,
            patch("cms.handlers.App.objects.get") as mock_get_app,
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        # Should return early without looking up models
        mock_get_instance.assert_not_called()
        mock_get_app.assert_not_called()
        # Status on fixtures should be unchanged
        assert mock_instance.status == ResourceStatus.PROVISIONING.value
        assert mock_app.status == ResourceStatus.PROVISIONING.value

    # -------------------------------------------------------------------------
    # Message formats
    # -------------------------------------------------------------------------

    def test_handles_multiple_message_formats(self, mock_instance, mock_app):
        """process_ngfw_event handles raw dict and JSON string formats."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.READY.value,
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            # Raw dict (no SNS wrapper)
            process_ngfw_event(event)
            assert mock_instance.status == ResourceStatus.READY.value

            # Reset status for next test
            mock_instance.status = ResourceStatus.PROVISIONING.value
            mock_instance.save.reset_mock()

            # JSON string
            process_ngfw_event(json.dumps(event))
            assert mock_instance.status == ResourceStatus.READY.value

    # -------------------------------------------------------------------------
    # Serial number handling
    # -------------------------------------------------------------------------

    def test_stores_serial_number_in_app_data(self, mock_instance, mock_app):
        """process_ngfw_event stores serial_number in App.data."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.READY.value,
            "serial_number": "007951000123456",
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert mock_app.data.get("serial_number") == "007951000123456"
        mock_app.save.assert_called_once_with(update_fields=["status", "data"])

    def test_serial_number_not_stored_when_not_provided(self, mock_instance, mock_app):
        """process_ngfw_event does not add serial_number when not in event."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.READY.value,
            # No serial_number field
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert "serial_number" not in mock_app.data

    def test_serial_number_preserves_existing_app_data(self, mock_instance, mock_app):
        """process_ngfw_event preserves existing App.data when adding serial."""
        mock_app.data = {"existing_key": "existing_value"}

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            "status": ResourceStatus.READY.value,
            "serial_number": "007951000123456",
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert mock_app.data.get("existing_key") == "existing_value"
        assert mock_app.data.get("serial_number") == "007951000123456"

    def test_serial_number_stored_without_status_update(self, mock_instance, mock_app):
        """process_ngfw_event can store serial_number even without status."""
        original_status = mock_app.status

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(mock_instance.id),
            "app_id": str(mock_app.id),
            # No status field - only serial_number
            "serial_number": "007951000123456",
        }

        with (
            patch("cms.handlers.Instance.objects.get", return_value=mock_instance),
            patch("cms.handlers.App.objects.get", return_value=mock_app),
        ):
            from cms.handlers import process_ngfw_event

            process_ngfw_event(make_sns_message(event))

        assert mock_app.status == original_status  # Status unchanged
        assert mock_app.data.get("serial_number") == "007951000123456"
        mock_app.save.assert_called_once_with(update_fields=["data"])
