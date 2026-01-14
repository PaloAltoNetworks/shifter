"""CMS NGFW handler tests.

Tests for process_ngfw_event handler function:
- Handles ngfw.event events (unified NGFW lifecycle events)
- Updates CMS Instance and App status
- Validates required fields (instance_id, app_id)
- Handles missing Instance/App gracefully
- Validates status values
"""

import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms.handlers import process_ngfw_event
from cms.models import App, Instance, Request
from shared.enums import RequestType, ResourceStatus
from shared.messages.events import EVENT_TYPE_NGFW

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="test@example.com", email="test@example.com")


@pytest.fixture
def instance_type(db):
    """Create InstanceType for testing."""
    from cms.models import InstanceType

    instance_type, _ = InstanceType.objects.get_or_create(
        slug="panw-ngfw",
        defaults={
            "name": "PANW NGFW",
            "spec_class": "shared.schemas.range.InstanceSpec",
        },
    )
    return instance_type


@pytest.fixture
def app_type(db):
    """Create AppType for testing."""
    from cms.models import AppType

    app_type, _ = AppType.objects.get_or_create(
        slug="panw-ngfw",
        defaults={
            "name": "Palo Alto Networks VM-Series",
            "spec_class": "shared.schemas.app.NGFWAppSpec",
        },
    )
    return app_type


@pytest.fixture
def cms_request(user, db):
    """Create a CMS Request for testing."""
    from uuid import uuid4

    return Request.objects.create(
        user=user,
        request_id=uuid4(),
        request_type=RequestType.NGFW.value,
    )


@pytest.fixture
def cms_instance(cms_request, instance_type, db):
    """Create a CMS Instance for testing."""
    return Instance.objects.create(
        request=cms_request,
        name="Test NGFW Instance",
        instance_type=instance_type,
        status=ResourceStatus.PROVISIONING.value,
    )


@pytest.fixture
def cms_app(cms_instance, app_type, db):
    """Create a CMS App for testing."""
    return App.objects.create(
        instance=cms_instance,
        name="Test NGFW App",
        app_type=app_type,
        status=ResourceStatus.PROVISIONING.value,
    )


def make_sns_message(event: dict) -> dict:
    """Wrap event in SNS envelope."""
    return {"Message": json.dumps(event)}


@pytest.mark.django_db
class TestProcessNgfwEvent:
    """Tests for process_ngfw_event handler."""

    # -------------------------------------------------------------------------
    # ngfw.event - status updates
    # -------------------------------------------------------------------------

    def test_updates_status_on_ngfw_event(self, cms_instance, cms_app):
        """process_ngfw_event updates Instance and App status."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_instance.refresh_from_db()
        cms_app.refresh_from_db()
        assert cms_instance.status == ResourceStatus.READY.value
        assert cms_app.status == ResourceStatus.READY.value

    def test_updates_to_failed_status(self, cms_instance, cms_app):
        """process_ngfw_event can update to FAILED status."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.FAILED.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_instance.refresh_from_db()
        cms_app.refresh_from_db()
        assert cms_instance.status == ResourceStatus.FAILED.value
        assert cms_app.status == ResourceStatus.FAILED.value

    def test_updates_to_destroyed_status(self, cms_instance, cms_app):
        """process_ngfw_event can update to DESTROYED status."""
        cms_instance.status = ResourceStatus.DESTROYING.value
        cms_instance.save()
        cms_app.status = ResourceStatus.DESTROYING.value
        cms_app.save()

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.DESTROYED.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_instance.refresh_from_db()
        cms_app.refresh_from_db()
        assert cms_instance.status == ResourceStatus.DESTROYED.value
        assert cms_app.status == ResourceStatus.DESTROYED.value

    def test_event_without_status_does_not_change_status(self, cms_instance, cms_app):
        """process_ngfw_event with no status field leaves status unchanged."""
        original_instance_status = cms_instance.status
        original_app_status = cms_app.status

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            # No status field
        }

        process_ngfw_event(make_sns_message(event))

        cms_instance.refresh_from_db()
        cms_app.refresh_from_db()
        assert cms_instance.status == original_instance_status
        assert cms_app.status == original_app_status

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_ignores_unknown_event_type(self, cms_instance, cms_app):
        """process_ngfw_event ignores unknown event types."""
        event = {
            "event_type": "ngfw.unknown.event",
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_instance.refresh_from_db()
        cms_app.refresh_from_db()
        # Status should remain unchanged
        assert cms_instance.status == ResourceStatus.PROVISIONING.value
        assert cms_app.status == ResourceStatus.PROVISIONING.value

    def test_handles_missing_instance_or_app_gracefully(self, cms_instance, cms_app):
        """process_ngfw_event handles missing Instance or App gracefully."""
        # Missing instance
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(uuid4()),  # Non-existent
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
        }
        process_ngfw_event(make_sns_message(event))  # Should not raise

        # Missing app
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(uuid4()),  # Non-existent
            "status": ResourceStatus.READY.value,
        }
        process_ngfw_event(make_sns_message(event))  # Should not raise

    def test_handles_missing_required_ids(self, cms_instance, cms_app):
        """process_ngfw_event handles events missing instance_id or app_id."""
        # Missing instance_id
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
        }
        process_ngfw_event(make_sns_message(event))  # Should not raise

        # Missing app_id
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "status": ResourceStatus.READY.value,
        }
        process_ngfw_event(make_sns_message(event))  # Should not raise

    def test_rejects_invalid_status(self, cms_instance, cms_app):
        """process_ngfw_event rejects invalid status values."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": "invalid_status",
        }

        process_ngfw_event(make_sns_message(event))

        # Status should remain unchanged
        cms_instance.refresh_from_db()
        cms_app.refresh_from_db()
        assert cms_instance.status == ResourceStatus.PROVISIONING.value
        assert cms_app.status == ResourceStatus.PROVISIONING.value

    # -------------------------------------------------------------------------
    # Message formats
    # -------------------------------------------------------------------------

    def test_handles_multiple_message_formats(self, cms_instance, cms_app):
        """process_ngfw_event handles raw dict and JSON string formats."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
        }

        # Raw dict (no SNS wrapper)
        process_ngfw_event(event)
        cms_instance.refresh_from_db()
        assert cms_instance.status == ResourceStatus.READY.value

        # Reset status for next test
        cms_instance.status = ResourceStatus.PROVISIONING.value
        cms_instance.save()

        # JSON string
        process_ngfw_event(json.dumps(event))
        cms_instance.refresh_from_db()
        assert cms_instance.status == ResourceStatus.READY.value

    # -------------------------------------------------------------------------
    # Serial number handling
    # -------------------------------------------------------------------------

    def test_stores_serial_number_in_app_data(self, cms_instance, cms_app):
        """process_ngfw_event stores serial_number in App.data."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
            "serial_number": "007951000123456",
        }

        process_ngfw_event(make_sns_message(event))

        cms_app.refresh_from_db()
        assert cms_app.data.get("serial_number") == "007951000123456"

    def test_serial_number_not_stored_when_not_provided(self, cms_instance, cms_app):
        """process_ngfw_event does not add serial_number when not in event."""
        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
            # No serial_number field
        }

        process_ngfw_event(make_sns_message(event))

        cms_app.refresh_from_db()
        assert "serial_number" not in cms_app.data

    def test_serial_number_preserves_existing_app_data(self, cms_instance, cms_app):
        """process_ngfw_event preserves existing App.data when adding serial."""
        # Pre-populate App.data with existing values
        cms_app.data = {"existing_key": "existing_value"}
        cms_app.save()

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            "status": ResourceStatus.READY.value,
            "serial_number": "007951000123456",
        }

        process_ngfw_event(make_sns_message(event))

        cms_app.refresh_from_db()
        assert cms_app.data.get("existing_key") == "existing_value"
        assert cms_app.data.get("serial_number") == "007951000123456"

    def test_serial_number_stored_without_status_update(self, cms_instance, cms_app):
        """process_ngfw_event can store serial_number even without status."""
        original_status = cms_app.status

        event = {
            "event_type": EVENT_TYPE_NGFW,
            "instance_id": str(cms_instance.id),
            "app_id": str(cms_app.id),
            # No status field - only serial_number
            "serial_number": "007951000123456",
        }

        process_ngfw_event(make_sns_message(event))

        cms_app.refresh_from_db()
        assert cms_app.status == original_status  # Status unchanged
        assert cms_app.data.get("serial_number") == "007951000123456"
