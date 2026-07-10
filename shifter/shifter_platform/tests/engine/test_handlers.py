"""Behavior tests for the Engine SNS event handlers.

The engine handlers consume range/ngfw events published by the provisioner and
update the real ``Range`` model (status, timestamps, provisioned instances) plus
record an audit row. These tests drive the handlers against real rows and assert
the persisted effect, instead of mocking ``Range.objects`` / the audit helper /
the sub-handlers.
"""

import json
import logging
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.handlers import process_event, process_range_event
from engine.models import Range
from risk_register.models import AuditLog
from shared.enums import ResourceStatus

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-handlers@example.com", email="engine-handlers@example.com")


def _sns(payload):
    return {"Message": json.dumps(payload)}


def _status_event(range_obj, *, new_status, **extra):
    return _sns(
        {
            "event_type": "range.status.updated",
            "range_id": range_obj.id,
            "user_id": range_obj.user_id,
            "new_status": new_status,
            **extra,
        }
    )


class TestProcessEventRouting:
    def test_routes_range_event_to_range_handler(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        process_event(_status_event(range_obj, new_status=ResourceStatus.PROVISIONING.value))
        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.PROVISIONING.value

    def test_ignores_unknown_event_type(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        process_event(_sns({"event_type": "range.unknown", "range_id": range_obj.id, "user_id": user.id}))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PENDING


class TestParseSnsMessage:
    def test_unwraps_sns_envelope(self):
        from engine.handlers import parse_sns_message

        result = parse_sns_message(_sns({"event_type": "range.status.updated", "range_id": 1}))
        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1

    def test_parses_string_input(self):
        from engine.handlers import parse_sns_message

        result = parse_sns_message(json.dumps(_sns({"event_type": "range.status.updated"})))
        assert result["event_type"] == "range.status.updated"

    def test_handles_non_wrapped_message(self):
        from engine.handlers import parse_sns_message

        assert parse_sns_message({"event_type": "range.status.updated"})["event_type"] == "range.status.updated"


class TestProcessRangeEventStatusUpdates:
    def test_updates_status(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        process_range_event(_status_event(range_obj, new_status=ResourceStatus.PROVISIONING.value))
        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.PROVISIONING.value

    def test_sets_ready_at_on_ready(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING, ready_at=None)
        process_range_event(_status_event(range_obj, new_status=ResourceStatus.READY.value))
        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.READY.value
        assert range_obj.ready_at is not None

    def test_sets_destroyed_at_on_destroyed(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.DESTROYING, destroyed_at=None)
        process_range_event(_status_event(range_obj, new_status=ResourceStatus.DESTROYED.value))
        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.DESTROYED.value
        assert range_obj.destroyed_at is not None

    def test_stores_error_message_on_failed(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING)
        process_range_event(
            _status_event(range_obj, new_status=ResourceStatus.FAILED.value, error_message="subnet exhausted")
        )
        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.FAILED.value
        assert range_obj.error_message == "subnet exhausted"

    def test_records_an_audit_row(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        before = AuditLog.objects.count()
        process_range_event(_status_event(range_obj, new_status=ResourceStatus.PROVISIONING.value))
        assert AuditLog.objects.count() > before

    def test_advances_updated_at(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        # auto_now is bypassed by save(update_fields=...), so force a stale
        # baseline that the handler must overwrite.
        stale = timezone.now() - timedelta(hours=1)
        Range.objects.filter(id=range_obj.id).update(updated_at=stale)
        process_range_event(_status_event(range_obj, new_status=ResourceStatus.PROVISIONING.value))
        range_obj.refresh_from_db()
        assert range_obj.updated_at > stale


class TestProcessRangeEventInvalidInputs:
    def test_ignores_unknown_event_type(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        process_range_event(_sns({"event_type": "range.other", "range_id": range_obj.id, "user_id": user.id}))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PENDING

    def test_handles_missing_range(self, user, caplog):
        # No row with this id: handler logs a warning and makes no change.
        before = AuditLog.objects.count()
        with caplog.at_level(logging.WARNING, logger="engine"):
            process_range_event(
                _sns(
                    {
                        "event_type": "range.status.updated",
                        "range_id": 999999,
                        "user_id": user.id,
                        "new_status": "ready",
                    }
                )
            )
        assert "999999" in caplog.text
        assert AuditLog.objects.count() == before

    def test_ignores_user_id_mismatch(self, user, django_user_model):
        other = django_user_model.objects.create_user(username="eh-other@example.com", email="eh-other@example.com")
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        # Event claims a different user than the range owner.
        process_range_event(
            _sns(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "user_id": other.id,
                    "new_status": ResourceStatus.READY.value,
                }
            )
        )
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PENDING


class TestProcessRangeEventTransientErrors:
    def test_db_save_error_propagates(self, user):
        """A transient DB save failure in _handle_status_updated raises.

        The worker must not ack the message when the DB call fails; propagating
        the exception causes the SQS visibility timeout to expire so the message
        is redelivered (DLQ backstops poison).
        """
        from django.db.models.signals import pre_save

        from engine.models import Range

        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        target_pk = range_obj.pk

        def _fail_if_target(sender, instance, **kwargs):
            if instance.pk == target_pk:
                raise Exception("DB connection error")

        pre_save.connect(_fail_if_target, sender=Range)
        try:
            with pytest.raises(Exception, match="DB connection error"):
                process_range_event(_status_event(range_obj, new_status=ResourceStatus.READY.value))
        finally:
            pre_save.disconnect(_fail_if_target, sender=Range)

    def test_permanent_early_returns_still_ack(self, user):
        """Permanent validation failures (missing range, user mismatch) still ack (return)."""
        # Missing range_id → returns, no exception
        process_range_event(
            _sns(
                {
                    "event_type": "range.status.updated",
                    "range_id": 999999,
                    "user_id": user.id,
                    "new_status": ResourceStatus.READY.value,
                }
            )
        )


class TestProcessRangeEventLogging:
    def test_logs_on_successful_update(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        with caplog.at_level(logging.INFO, logger="engine"):
            process_range_event(_status_event(range_obj, new_status=ResourceStatus.PROVISIONING.value))
        assert str(range_obj.id) in caplog.text


class TestHandleProvisioned:
    """range.provisioned is an audit-trail log only; the provisioner writes the
    instance/subnet state directly, so the handler makes no DB change."""

    def test_logs_but_does_not_modify_range(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING, provisioned_instances=None)
        request_id = "req-abc"
        with caplog.at_level(logging.INFO, logger="engine"):
            process_range_event(
                _sns(
                    {
                        "event_type": "range.provisioned",
                        "range_id": range_obj.id,
                        "user_id": user.id,
                        "request_id": request_id,
                    }
                )
            )
        assert request_id in caplog.text
        range_obj.refresh_from_db()
        # No DB mutation: status and provisioned_instances are untouched.
        assert range_obj.status == Range.Status.PROVISIONING
        assert range_obj.provisioned_instances is None

    def test_handles_event_without_range_in_db(self, user, caplog):
        # No matching range_id: handler is a log-only no-op, no exception.
        before = AuditLog.objects.count()
        with caplog.at_level(logging.INFO, logger="engine"):
            process_range_event(_sns({"event_type": "range.provisioned", "range_id": 999999, "user_id": user.id}))
        assert "999999" in caplog.text
        assert AuditLog.objects.count() == before


class TestProcessNgfwEvent:
    """The engine NGFW handler is notification/audit-only: it records one
    AuditLog row for the NGFW lifecycle event.

    An NGFW is identified by UUIDs (app_id / instance_id), but AuditLog.entity_id
    is a PositiveIntegerField. Feeding the UUID app_id as entity_id makes the
    audit write fail (silently, since audit_log swallows and returns None), so
    the row is lost. entity_id must stay an int; the UUID identifiers belong in
    the audit state.
    """

    def _ngfw_event(self, **extra):
        return _sns(
            {
                "event_type": "ngfw.event",
                "event_id": "evt-ngfw-1",
                "request_id": "req-ngfw-1",
                "instance_id": "11111111-1111-1111-1111-111111111111",
                "app_id": "22222222-2222-2222-2222-222222222222",
                "status": ResourceStatus.READY.value,
                **extra,
            }
        )

    def test_records_audit_row_with_uuid_identifiers(self, user):
        from engine.handlers import process_ngfw_event

        before = AuditLog.objects.count()
        process_ngfw_event(self._ngfw_event())
        assert AuditLog.objects.count() == before + 1

        row = AuditLog.objects.filter(entity_type=AuditLog.EntityType.NGFW).latest("timestamp")
        # entity_id is an int column; the UUID app_id must NOT be jammed into it.
        assert row.entity_id == 0
        # The UUID identifiers are preserved in the audit state instead.
        assert row.new_state["app_id"] == "22222222-2222-2222-2222-222222222222"
        assert row.new_state["instance_id"] == "11111111-1111-1111-1111-111111111111"
        assert row.new_state["status"] == ResourceStatus.READY.value

    def test_ignores_non_ngfw_event_type(self, user):
        from engine.handlers import process_ngfw_event

        before = AuditLog.objects.count()
        process_ngfw_event(_sns({"event_type": "range.status.updated", "range_id": 1, "user_id": user.id}))
        assert AuditLog.objects.count() == before
