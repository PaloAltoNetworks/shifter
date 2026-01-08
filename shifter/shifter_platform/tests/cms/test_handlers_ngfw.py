"""CMS NGFW handler tests.

Tests for process_ngfw_event handler function:
- Handles ngfw.status.updated events
- Updates CMS NGFW.status
- Validates user_id matches
- Handles missing NGFW gracefully
- Validates status values
"""

import json

import pytest
from django.contrib.auth import get_user_model

from cms.handlers import process_ngfw_event
from cms.models import NGFW
from shared.enums import InstanceStatus

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="test@example.com", email="test@example.com"
    )


@pytest.fixture
def cms_ngfw(user, db):
    """Create a CMS NGFW for testing."""
    return NGFW.objects.create(
        user=user,
        name="Test NGFW",
        status=InstanceStatus.PROVISIONING.value,
    )


def make_sns_message(event: dict) -> dict:
    """Wrap event in SNS envelope."""
    return {"Message": json.dumps(event)}


@pytest.mark.django_db
class TestProcessNgfwEvent:
    """Tests for process_ngfw_event handler."""

    # -------------------------------------------------------------------------
    # ngfw.status.updated event
    # -------------------------------------------------------------------------

    def test_updates_status_on_status_event(self, cms_ngfw):
        """process_ngfw_event updates CMS NGFW status."""
        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "ngfw_id": 1,  # Engine's ID
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.READY.value

    def test_updates_to_active_status(self, cms_ngfw):
        """process_ngfw_event can update to ACTIVE status."""
        cms_ngfw.status = InstanceStatus.STARTING.value
        cms_ngfw.save()

        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.ACTIVE.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.ACTIVE.value

    def test_updates_to_stopped_status(self, cms_ngfw):
        """process_ngfw_event can update to STOPPED status."""
        cms_ngfw.status = InstanceStatus.STOPPING.value
        cms_ngfw.save()

        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.STOPPED.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.STOPPED.value

    def test_updates_to_failed_status(self, cms_ngfw):
        """process_ngfw_event can update to FAILED status."""
        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.FAILED.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.FAILED.value

    def test_updates_to_deprovisioned_status(self, cms_ngfw):
        """process_ngfw_event can update to DEPROVISIONED status."""
        cms_ngfw.status = InstanceStatus.DEPROVISIONING.value
        cms_ngfw.save()

        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.DEPROVISIONED.value,
        }

        process_ngfw_event(make_sns_message(event))

        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.DEPROVISIONED.value

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_ignores_unknown_event_type(self, cms_ngfw, caplog):
        """process_ngfw_event ignores unknown event types."""
        event = {
            "event_type": "ngfw.unknown.event",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
        }

        process_ngfw_event(make_sns_message(event))

        cms_ngfw.refresh_from_db()
        # Status should remain unchanged
        assert cms_ngfw.status == InstanceStatus.PROVISIONING.value

    def test_ignores_provisioned_event(self, cms_ngfw, caplog):
        """process_ngfw_event ignores ngfw.provisioned (Engine handles it)."""
        event = {
            "event_type": "ngfw.provisioned",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "instance_id": "i-1234567890abcdef0",
        }

        process_ngfw_event(make_sns_message(event))

        cms_ngfw.refresh_from_db()
        # Status should remain unchanged
        assert cms_ngfw.status == InstanceStatus.PROVISIONING.value

    def test_handles_missing_ngfw(self, db, caplog):
        """process_ngfw_event logs warning for missing NGFW."""
        import logging

        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": 99999,
            "user_id": 1,
            "new_status": InstanceStatus.READY.value,
        }

        with caplog.at_level(logging.WARNING, logger="cms.handlers"):
            process_ngfw_event(make_sns_message(event))

        assert "not found" in caplog.text.lower()

    def test_rejects_user_id_mismatch(self, cms_ngfw, caplog):
        """process_ngfw_event rejects events with wrong user_id."""
        import logging

        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": 99999,  # Wrong user
            "new_status": InstanceStatus.READY.value,
        }

        with caplog.at_level(logging.ERROR, logger="cms.handlers"):
            process_ngfw_event(make_sns_message(event))

        # Status should remain unchanged
        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.PROVISIONING.value
        assert "mismatch" in caplog.text.lower()

    def test_rejects_invalid_status(self, cms_ngfw, caplog):
        """process_ngfw_event rejects invalid status values."""
        import logging

        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": "invalid_status",
        }

        with caplog.at_level(logging.ERROR, logger="cms.handlers"):
            process_ngfw_event(make_sns_message(event))

        # Status should remain unchanged
        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.PROVISIONING.value
        assert "invalid" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Message formats
    # -------------------------------------------------------------------------

    def test_handles_raw_dict_event(self, cms_ngfw):
        """process_ngfw_event handles raw dict (no SNS wrapper)."""
        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        process_ngfw_event(event)  # Raw dict, no SNS wrapper

        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.READY.value

    def test_handles_json_string_event(self, cms_ngfw):
        """process_ngfw_event handles JSON string directly."""
        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        process_ngfw_event(json.dumps(event))  # JSON string

        cms_ngfw.refresh_from_db()
        assert cms_ngfw.status == InstanceStatus.READY.value

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_info_on_status_update(self, cms_ngfw, caplog):
        """process_ngfw_event logs info on successful status update."""
        import logging

        event = {
            "event_type": "ngfw.status.updated",
            "cms_ngfw_id": cms_ngfw.id,
            "user_id": cms_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        with caplog.at_level(logging.INFO, logger="cms.handlers"):
            process_ngfw_event(make_sns_message(event))

        assert "NGFW" in caplog.text or str(cms_ngfw.id) in caplog.text
