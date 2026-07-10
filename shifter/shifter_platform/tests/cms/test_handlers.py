"""Behavior tests for CMS event handlers.

The CMS handlers consume range/ngfw events published by the Engine
and update real CMS rows: ``process_range_event`` updates ``RangeInstance`` and
fires the ``range_status_changed`` signal (the CTF decoupling bridge);
``process_event`` routes by event-type prefix. These tests drive the handlers
against real ``RangeInstance``/``Request``/``Instance``/``App`` rows and assert
the persisted effect (and the real signal firing), instead of patching
``RangeInstance``, the sub-handlers, or the bridge functions.
"""

import json
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.handlers import parse_sns_message, process_event, process_range_event
from cms.models import App, AppType, Instance, InstanceType, RangeInstance, Request
from cms.signals import range_status_changed
from shared.enums import RequestType, ResourceStatus

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-handlers@example.com", email="cms-handlers@example.com")


def _sns(payload: dict) -> dict:
    """Wrap an event payload in the SNS envelope the worker delivers."""
    return {"Message": json.dumps(payload)}


def _range_event(*, new_status, user_id, range_id=None, request_id=None, **extra) -> dict:
    payload = {"event_type": "range.status.updated", "new_status": new_status, "user_id": user_id, **extra}
    if range_id is not None:
        payload["range_id"] = range_id
    if request_id is not None:
        payload["request_id"] = str(request_id)
    return _sns(payload)


def _range_instance(user, *, range_id=None, request=None, status=ResourceStatus.PENDING.value, scenario_id="basic"):
    return RangeInstance.objects.create(
        user_id=user.id, range_id=range_id, request=request, status=status, scenario_id=scenario_id
    )


def _request(user) -> Request:
    return Request.objects.create(request_id=uuid4(), request_type=RequestType.RANGE.value, user=user)


@pytest.fixture
def ctf_signal():
    """Record ``range_status_changed`` deliveries (the real CTF bridge signal)."""
    received: list[dict] = []

    def receiver(sender, **kwargs):
        received.append(kwargs)

    range_status_changed.connect(receiver, weak=False)
    try:
        yield received
    finally:
        range_status_changed.disconnect(receiver)


# -----------------------------------------------------------------------------
# Dispatcher routing (process_event)
# -----------------------------------------------------------------------------


class TestProcessEventRouting:
    def test_routes_range_events_to_range_handler(self, user):
        ri = _range_instance(user, range_id=1)
        process_event(_range_event(range_id=1, new_status=ResourceStatus.PROVISIONING.value, user_id=user.id))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PROVISIONING.value

    def test_routes_ngfw_events_to_ngfw_handler(self, user):
        instance, app = _make_instance_and_app(user)
        message = _sns(
            {
                "event_type": "ngfw.event",
                "instance_id": str(instance.id),
                "app_id": str(app.id),
                "status": ResourceStatus.READY.value,
            }
        )
        process_event(message)
        instance.refresh_from_db()
        app.refresh_from_db()
        assert instance.status == ResourceStatus.READY.value
        assert app.status == ResourceStatus.READY.value

    def test_ignores_unknown_event_types(self, user):
        ri = _range_instance(user, range_id=2)
        process_event(_sns({"event_type": "unknown.event", "range_id": 2, "user_id": user.id}))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PENDING.value

    def test_handles_missing_event_type(self, user):
        ri = _range_instance(user, range_id=3)
        process_event(_sns({"range_id": 3, "user_id": user.id}))  # must not raise
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PENDING.value


# -----------------------------------------------------------------------------
# SNS envelope parsing (parse_sns_message) — pure helper, no boundaries
# -----------------------------------------------------------------------------


class TestParseSnsMessage:
    def test_unwraps_sns_envelope(self):
        result = parse_sns_message(_sns({"event_type": "range.status.updated", "range_id": 1, "user_id": 42}))
        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1
        assert result["user_id"] == 42

    def test_parses_string_input(self):
        raw = json.dumps(_sns({"event_type": "range.status.updated", "range_id": 1}))
        result = parse_sns_message(raw)
        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1

    def test_handles_non_wrapped_message(self):
        direct = {"event_type": "range.status.updated", "range_id": 1, "user_id": 42}
        result = parse_sns_message(direct)
        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1


# -----------------------------------------------------------------------------
# process_range_event — status updates
# -----------------------------------------------------------------------------


class TestProcessRangeEventStatusUpdates:
    def test_updates_range_instance_status(self, user, ctf_signal):
        ri = _range_instance(user, range_id=1, status=ResourceStatus.PENDING.value)
        process_range_event(_range_event(range_id=1, new_status=ResourceStatus.PROVISIONING.value, user_id=user.id))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PROVISIONING.value
        # CTF bridge fired once with the real before/after statuses.
        assert len(ctf_signal) == 1
        assert ctf_signal[0]["range_instance_id"] == ri.pk
        assert ctf_signal[0]["new_status"] == ResourceStatus.PROVISIONING.value
        assert ctf_signal[0]["previous_status"] == ResourceStatus.PENDING.value

    def test_handles_ready_status(self, user):
        ri = _range_instance(user, range_id=2, status=ResourceStatus.PROVISIONING.value)
        process_range_event(_range_event(range_id=2, new_status=ResourceStatus.READY.value, user_id=user.id))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.READY.value

    def test_terminal_status_soft_deletes_instance(self, user):
        """DESTROYED is terminal: status persists and the row is soft-deleted."""
        ri = _range_instance(user, range_id=3, status=ResourceStatus.DESTROYING.value)
        process_range_event(_range_event(range_id=3, new_status=ResourceStatus.DESTROYED.value, user_id=user.id))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.DESTROYED.value
        assert ri.deleted_at is not None
        # Soft-deleted: the active manager no longer surfaces it.
        assert not RangeInstance.objects.filter(pk=ri.pk).exists()
        assert RangeInstance.all_objects.filter(pk=ri.pk).exists()


# -----------------------------------------------------------------------------
# process_range_event — ignored / invalid inputs
# -----------------------------------------------------------------------------


class TestProcessRangeEventInvalidInputs:
    def test_ignores_non_status_events(self, user, ctf_signal):
        ri = _range_instance(user, range_id=4, status=ResourceStatus.PENDING.value)
        process_range_event(_sns({"event_type": "range.provisioned", "range_id": 4, "user_id": user.id}))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PENDING.value
        assert ctf_signal == []

    def test_handles_missing_range_instance(self, user, ctf_signal):
        """No matching RangeInstance: nothing changes and the bridge does not fire."""
        process_range_event(_range_event(range_id=999, new_status=ResourceStatus.READY.value, user_id=user.id))
        assert ctf_signal == []

    def test_handles_user_id_mismatch(self, user, ctf_signal):
        ri = _range_instance(user, range_id=5, status=ResourceStatus.PENDING.value)
        process_range_event(_range_event(range_id=5, new_status=ResourceStatus.READY.value, user_id=999))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PENDING.value
        assert ctf_signal == []

    def test_rejects_invalid_status_value(self, user, ctf_signal):
        ri = _range_instance(user, range_id=50, status=ResourceStatus.PENDING.value)
        process_range_event(_range_event(range_id=50, new_status="bogus_status", user_id=user.id))
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PENDING.value
        assert ctf_signal == []


# -----------------------------------------------------------------------------
# process_range_event — request_id correlation
# -----------------------------------------------------------------------------


class TestProcessRangeEventRequestLookup:
    def test_lookup_by_request_id_when_range_id_is_none(self, user):
        """Resolves via Request.request_id and persists the event's range_id."""
        req = _request(user)
        ri = _range_instance(user, request=req, range_id=None, status=ResourceStatus.PENDING.value)
        process_range_event(
            _range_event(
                request_id=req.request_id, range_id=57, new_status=ResourceStatus.FAILED.value, user_id=user.id
            )
        )
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.FAILED.value
        assert ri.range_id == 57  # was None, now set from the event

    def test_range_id_not_overwritten_if_already_set(self, user):
        req = _request(user)
        ri = _range_instance(user, request=req, range_id=10, status=ResourceStatus.PENDING.value)
        process_range_event(
            _range_event(
                request_id=req.request_id, range_id=99, new_status=ResourceStatus.PROVISIONING.value, user_id=user.id
            )
        )
        ri.refresh_from_db()
        assert ri.status == ResourceStatus.PROVISIONING.value
        assert ri.range_id == 10  # existing value preserved

    def test_request_id_lookup_preferred_over_range_id(self, user):
        """When both ids are present, the row correlated by request_id wins.

        The event's ``range_id`` points at a decoy row; only the request-linked
        target is updated, proving the lookup is by request_id.
        """
        req = _request(user)
        target = _range_instance(user, request=req, range_id=77, status=ResourceStatus.PENDING.value)
        decoy = _range_instance(user, range_id=55, status=ResourceStatus.PENDING.value)
        process_range_event(
            _range_event(request_id=req.request_id, range_id=55, new_status=ResourceStatus.READY.value, user_id=user.id)
        )
        target.refresh_from_db()
        decoy.refresh_from_db()
        assert target.status == ResourceStatus.READY.value
        assert decoy.status == ResourceStatus.PENDING.value

    def test_destroyed_event_can_update_soft_deleted_request_range(self, user):
        """Destroy hides the CMS row early; the final DESTROYED event still lands.

        The row is soft-deleted at ``destroying`` time, so the active manager
        cannot see it. The destroyed event resolves it through the unfiltered
        manager and marks it destroyed.
        """
        req = _request(user)
        ri = _range_instance(user, request=req, range_id=14, status=ResourceStatus.DESTROYING.value)
        ri.deleted_at = timezone.now()
        ri.save(update_fields=["deleted_at"])
        assert not RangeInstance.objects.filter(pk=ri.pk).exists()  # hidden from active manager

        process_range_event(
            _range_event(
                request_id=req.request_id, range_id=14, new_status=ResourceStatus.DESTROYED.value, user_id=user.id
            )
        )

        ri.refresh_from_db()
        assert ri.status == ResourceStatus.DESTROYED.value


# -----------------------------------------------------------------------------
# Shared builders for the ngfw routing test
# -----------------------------------------------------------------------------


def _make_instance_and_app(user, *, status=ResourceStatus.PROVISIONING.value):
    req = _request(user)
    instance_type = InstanceType.objects.create(
        name="Handler Test Instance Type",
        slug=f"handler-it-{uuid4().hex[:8]}",
        spec_slug="credential.scm",
    )
    app_type = AppType.objects.create(
        name="Handler Test App Type",
        slug=f"handler-at-{uuid4().hex[:8]}",
        spec_slug="credential.scm",
    )
    instance = Instance.objects.create(request=req, name="ngfw-instance", instance_type=instance_type, status=status)
    app = App.objects.create(name="ngfw-app", app_type=app_type, instance=instance, status=status)
    return instance, app
