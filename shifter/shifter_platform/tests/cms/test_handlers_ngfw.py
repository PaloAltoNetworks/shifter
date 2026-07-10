"""Behavior tests for the CMS NGFW event handler.

``process_ngfw_event`` consumes unified ``ngfw.event`` messages and updates the
real CMS ``Instance`` and ``App`` rows (status, and ``App.data.serial_number``).
These tests drive the handler against real rows and assert the persisted effect,
instead of patching ``Instance.objects.get`` / ``App.objects.get``.
"""

import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from cms.handlers import process_ngfw_event
from cms.models import App, AppType, Instance, InstanceType, Request
from shared.enums import RequestType, ResourceStatus
from shared.messages.events import EVENT_TYPE_NGFW

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-ngfw@example.com", email="cms-ngfw@example.com")


@pytest.fixture
def request_obj(user):
    return Request.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=user)


@pytest.fixture
def instance(request_obj):
    instance_type = InstanceType.objects.create(
        name="NGFW Test Instance Type",
        slug=f"ngfw-it-{uuid4().hex[:8]}",
        spec_slug="credential.scm",
    )
    return Instance.objects.create(
        request=request_obj,
        name="ngfw-instance",
        instance_type=instance_type,
        status=ResourceStatus.PROVISIONING.value,
    )


@pytest.fixture
def app(instance):
    app_type = AppType.objects.create(
        name="NGFW Test App Type",
        slug=f"ngfw-at-{uuid4().hex[:8]}",
        spec_slug="credential.scm",
    )
    return App.objects.create(
        name="ngfw-app",
        app_type=app_type,
        instance=instance,
        status=ResourceStatus.PROVISIONING.value,
    )


def make_sns_message(event: dict) -> dict:
    """Wrap event in SNS envelope."""
    return {"Message": json.dumps(event)}


def _ngfw_event(instance_id, app_id, **extra) -> dict:
    return {"event_type": EVENT_TYPE_NGFW, "instance_id": str(instance_id), "app_id": str(app_id), **extra}


class TestProcessNgfwEventStatusUpdates:
    """Status update tests for process_ngfw_event()."""

    def test_updates_status_on_ngfw_event(self, instance, app):
        event = _ngfw_event(instance.id, app.id, status=ResourceStatus.READY.value)
        process_ngfw_event(make_sns_message(event))

        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value
        assert app.status == ResourceStatus.READY.value

    def test_updates_to_failed_status(self, instance, app):
        event = _ngfw_event(instance.id, app.id, status=ResourceStatus.FAILED.value)
        process_ngfw_event(make_sns_message(event))

        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.FAILED.value
        assert app.status == ResourceStatus.FAILED.value

    def test_updates_to_destroyed_status(self, instance, app):
        instance.status = ResourceStatus.DESTROYING.value
        instance.save(update_fields=["status"])
        app.status = ResourceStatus.DESTROYING.value
        app.save(update_fields=["status"])

        event = _ngfw_event(instance.id, app.id, status=ResourceStatus.DESTROYED.value)
        process_ngfw_event(make_sns_message(event))

        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.DESTROYED.value
        assert app.status == ResourceStatus.DESTROYED.value

    def test_event_without_status_does_not_change_status(self, instance, app):
        event = _ngfw_event(instance.id, app.id)  # no status field
        process_ngfw_event(make_sns_message(event))

        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.PROVISIONING.value
        assert app.status == ResourceStatus.PROVISIONING.value


class TestProcessNgfwEventInvalidInputs:
    """Ignored and invalid input tests for process_ngfw_event()."""

    def test_ignores_unknown_event_type(self, instance, app):
        event = _ngfw_event(instance.id, app.id, status=ResourceStatus.READY.value)
        event["event_type"] = "ngfw.unknown.event"
        process_ngfw_event(make_sns_message(event))

        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.PROVISIONING.value
        assert app.status == ResourceStatus.PROVISIONING.value

    def test_handles_missing_instance_gracefully(self, app):
        """Missing Instance does not stop processing — App is still updated."""
        event = _ngfw_event(uuid4(), app.id, status=ResourceStatus.READY.value)
        process_ngfw_event(make_sns_message(event))

        app.refresh_from_db()
        assert app.status == ResourceStatus.READY.value

    def test_handles_missing_app_gracefully(self, instance):
        """Missing App does not stop processing — Instance is still updated."""
        event = _ngfw_event(instance.id, uuid4(), status=ResourceStatus.READY.value)
        process_ngfw_event(make_sns_message(event))

        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value

    def test_handles_missing_required_ids(self, instance, app):
        """Events missing instance_id or app_id are ignored — no row changes."""
        process_ngfw_event(
            make_sns_message(
                {"event_type": EVENT_TYPE_NGFW, "app_id": str(app.id), "status": ResourceStatus.READY.value}
            )
        )
        process_ngfw_event(
            make_sns_message(
                {"event_type": EVENT_TYPE_NGFW, "instance_id": str(instance.id), "status": ResourceStatus.READY.value}
            )
        )

        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.PROVISIONING.value
        assert app.status == ResourceStatus.PROVISIONING.value

    def test_rejects_invalid_status(self, instance, app):
        event = _ngfw_event(instance.id, app.id, status="invalid_status")
        process_ngfw_event(make_sns_message(event))

        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.PROVISIONING.value
        assert app.status == ResourceStatus.PROVISIONING.value

    def test_handles_multiple_message_formats(self, instance, app):
        """process_ngfw_event accepts a raw dict and a JSON string envelope."""
        # Raw dict (no SNS wrapper).
        process_ngfw_event(_ngfw_event(instance.id, app.id, status=ResourceStatus.READY.value))
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value

        # JSON string.
        process_ngfw_event(json.dumps(_ngfw_event(instance.id, app.id, status=ResourceStatus.DESTROYED.value)))
        instance.refresh_from_db()
        assert instance.status == ResourceStatus.DESTROYED.value


class TestProcessNgfwEventSerialNumber:
    """Serial number payload tests for process_ngfw_event()."""

    def test_stores_serial_number_in_app_data(self, instance, app):
        event = _ngfw_event(instance.id, app.id, status=ResourceStatus.READY.value, serial_number="007951000123456")
        process_ngfw_event(make_sns_message(event))

        app.refresh_from_db()
        assert app.data.get("serial_number") == "007951000123456"
        assert app.status == ResourceStatus.READY.value

    def test_serial_number_not_stored_when_not_provided(self, instance, app):
        event = _ngfw_event(instance.id, app.id, status=ResourceStatus.READY.value)
        process_ngfw_event(make_sns_message(event))

        app.refresh_from_db()
        assert "serial_number" not in app.data

    def test_serial_number_preserves_existing_app_data(self, instance, app):
        app.data = {"existing_key": "existing_value"}
        app.save(update_fields=["data"])

        event = _ngfw_event(instance.id, app.id, status=ResourceStatus.READY.value, serial_number="007951000123456")
        process_ngfw_event(make_sns_message(event))

        app.refresh_from_db()
        assert app.data.get("existing_key") == "existing_value"
        assert app.data.get("serial_number") == "007951000123456"

    def test_serial_number_stored_without_status_update(self, instance, app):
        event = _ngfw_event(instance.id, app.id, serial_number="007951000123456")  # no status
        process_ngfw_event(make_sns_message(event))

        app.refresh_from_db()
        assert app.status == ResourceStatus.PROVISIONING.value  # unchanged
        assert app.data.get("serial_number") == "007951000123456"
