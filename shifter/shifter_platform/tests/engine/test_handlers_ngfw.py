"""Engine NGFW handler tests.

Tests for process_ngfw_event handler function:
- Handles ngfw.status.updated events
- Handles ngfw.provisioned events
- Updates Engine NGFW model
- Validates user_id matches
- Handles missing NGFW gracefully
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.handlers import process_ngfw_event
from engine.models import NGFW
from shared.enums import InstanceStatus

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="test@example.com", email="test@example.com"
    )


@pytest.fixture
def engine_ngfw(user, db):
    """Create an Engine NGFW for testing."""
    return NGFW.objects.create(
        user=user,
        cms_ngfw_id=100,
        status=InstanceStatus.PROVISIONING.value,
        ngfw_config={"role": "ngfw", "ngfw_app": {"name": "Test"}},
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

    def test_updates_status_on_status_event(self, engine_ngfw):
        """process_ngfw_event updates NGFW status."""
        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.status == InstanceStatus.READY.value

    def test_sets_provisioned_at_on_ready(self, engine_ngfw):
        """process_ngfw_event sets provisioned_at when status is READY."""
        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        before = timezone.now()
        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.provisioned_at is not None
        assert engine_ngfw.provisioned_at >= before

    def test_sets_last_started_at_on_active(self, engine_ngfw):
        """process_ngfw_event sets last_started_at when status is ACTIVE."""
        engine_ngfw.status = InstanceStatus.STARTING.value
        engine_ngfw.save()

        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.ACTIVE.value,
        }

        before = timezone.now()
        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.last_started_at is not None
        assert engine_ngfw.last_started_at >= before

    def test_sets_last_stopped_at_on_stopped(self, engine_ngfw):
        """process_ngfw_event sets last_stopped_at when status is STOPPED."""
        engine_ngfw.status = InstanceStatus.STOPPING.value
        engine_ngfw.save()

        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.STOPPED.value,
        }

        before = timezone.now()
        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.last_stopped_at is not None
        assert engine_ngfw.last_stopped_at >= before

    def test_sets_error_message_on_failed(self, engine_ngfw):
        """process_ngfw_event sets error_message when status is FAILED."""
        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.FAILED.value,
            "error_message": "Provisioning failed: timeout",
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.status == InstanceStatus.FAILED.value
        assert engine_ngfw.error_message == "Provisioning failed: timeout"

    # -------------------------------------------------------------------------
    # ngfw.provisioned event
    # -------------------------------------------------------------------------

    def test_updates_instance_id_on_provisioned(self, engine_ngfw):
        """process_ngfw_event updates instance_id on provisioned event."""
        event = {
            "event_type": "ngfw.provisioned",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "instance_id": "i-1234567890abcdef0",
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.instance_id == "i-1234567890abcdef0"

    def test_updates_management_ip_on_provisioned(self, engine_ngfw):
        """process_ngfw_event updates management_ip on provisioned event."""
        event = {
            "event_type": "ngfw.provisioned",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "management_ip": "10.0.1.100",
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert str(engine_ngfw.management_ip) == "10.0.1.100"

    def test_updates_dataplane_ip_on_provisioned(self, engine_ngfw):
        """process_ngfw_event updates dataplane_ip on provisioned event."""
        event = {
            "event_type": "ngfw.provisioned",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "dataplane_ip": "10.0.2.100",
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert str(engine_ngfw.dataplane_ip) == "10.0.2.100"

    def test_updates_gwlb_resources_on_provisioned(self, engine_ngfw):
        """process_ngfw_event updates GWLB resources on provisioned event."""
        event = {
            "event_type": "ngfw.provisioned",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "gwlb_arn": "arn:aws:elasticloadbalancing:us-east-2:123:gwlb/test",
            "target_group_arn": "arn:aws:elasticloadbalancing:us-east-2:123:tg/test",
            "service_name": "com.amazonaws.vpce.us-east-2.vpce-svc-123",
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert "gwlb/test" in engine_ngfw.gwlb_arn
        assert "tg/test" in engine_ngfw.target_group_arn
        assert "vpce-svc" in engine_ngfw.gwlb_service_name

    def test_updates_pulumi_stack_on_provisioned(self, engine_ngfw):
        """process_ngfw_event updates pulumi_stack on provisioned event."""
        event = {
            "event_type": "ngfw.provisioned",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "pulumi_stack": "ngfw-user-1-ngfw-42",
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.pulumi_stack == "ngfw-user-1-ngfw-42"

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    def test_ignores_unknown_event_type(self, engine_ngfw, caplog):
        """process_ngfw_event ignores unknown event types."""
        event = {
            "event_type": "ngfw.unknown.event",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
        }

        process_ngfw_event(make_sns_message(event))

        engine_ngfw.refresh_from_db()
        # Status should remain unchanged
        assert engine_ngfw.status == InstanceStatus.PROVISIONING.value

    def test_handles_missing_ngfw(self, db, caplog):
        """process_ngfw_event logs warning for missing NGFW."""
        import logging

        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": 99999,
            "user_id": 1,
            "new_status": InstanceStatus.READY.value,
        }

        with caplog.at_level(logging.WARNING, logger="engine.handlers"):
            process_ngfw_event(make_sns_message(event))

        assert "not found" in caplog.text.lower()

    def test_rejects_user_id_mismatch(self, engine_ngfw, caplog):
        """process_ngfw_event rejects events with wrong user_id."""
        import logging

        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": 99999,  # Wrong user
            "new_status": InstanceStatus.READY.value,
        }

        with caplog.at_level(logging.ERROR, logger="engine.handlers"):
            process_ngfw_event(make_sns_message(event))

        # Status should remain unchanged
        engine_ngfw.refresh_from_db()
        assert engine_ngfw.status == InstanceStatus.PROVISIONING.value
        assert "mismatch" in caplog.text.lower()

    def test_handles_raw_dict_event(self, engine_ngfw):
        """process_ngfw_event handles raw dict (no SNS wrapper)."""
        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        process_ngfw_event(event)  # Raw dict, no SNS wrapper

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.status == InstanceStatus.READY.value

    def test_handles_json_string_event(self, engine_ngfw):
        """process_ngfw_event handles JSON string directly."""
        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        process_ngfw_event(json.dumps(event))  # JSON string

        engine_ngfw.refresh_from_db()
        assert engine_ngfw.status == InstanceStatus.READY.value

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def test_logs_info_on_status_update(self, engine_ngfw, caplog):
        """process_ngfw_event logs info on successful status update."""
        import logging

        event = {
            "event_type": "ngfw.status.updated",
            "ngfw_id": engine_ngfw.id,
            "user_id": engine_ngfw.user_id,
            "new_status": InstanceStatus.READY.value,
        }

        with caplog.at_level(logging.INFO, logger="engine.handlers"):
            process_ngfw_event(make_sns_message(event))

        assert "NGFW" in caplog.text or str(engine_ngfw.id) in caplog.text
