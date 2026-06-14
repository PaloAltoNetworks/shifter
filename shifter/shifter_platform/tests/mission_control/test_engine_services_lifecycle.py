"""Behavior tests for engine range lifecycle services (destroy_range / cancel_range).

Drives the real services against real ``Range`` rows and asserts the persisted
status transition and return value. ECS teardown is unconfigured under test
settings, so it is a no-op and needs no boundary mock.
"""

import logging
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine import cancel_range, destroy_range
from engine.models import Range
from shared.enums import ResourceStatus
from shared.schemas import RangeContext

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="lifecycle@example.com", email="lifecycle@example.com")


def _ctx(*, range_id, user_id, status=ResourceStatus.READY):
    return RangeContext(
        request_id=uuid4(),
        range_id=range_id,
        user_id=user_id,
        scenario_id="test-scenario",
        status=status,
        instances=[],
    )


class TestDestroyRange:
    def test_sets_status_to_destroying_and_returns_true(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        result = destroy_range(_ctx(range_id=range_obj.id, user_id=user.id))
        assert result is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_returns_false_when_range_not_found(self, user, caplog):
        with caplog.at_level(logging.WARNING, logger="engine"):
            result = destroy_range(_ctx(range_id=999999, user_id=user.id))
        assert result is False
        assert "not found" in caplog.text.lower()

    def test_returns_false_when_already_destroyed(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.DESTROYED)
        with caplog.at_level(logging.WARNING, logger="engine"):
            result = destroy_range(_ctx(range_id=range_obj.id, user_id=user.id))
        assert result is False
        assert "already destroyed" in caplog.text.lower()

    def test_idempotent_when_already_destroying(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.DESTROYING)
        with caplog.at_level(logging.INFO, logger="engine"):
            result = destroy_range(_ctx(range_id=range_obj.id, user_id=user.id))
        assert result is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING
        assert "already destroying" in caplog.text.lower()

    def test_logs_range_id_on_entry(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        with caplog.at_level(logging.DEBUG, logger="engine"):
            destroy_range(_ctx(range_id=range_obj.id, user_id=user.id))
        assert str(range_obj.id) in caplog.text


class TestCancelRange:
    def test_cancels_pending_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        cancel_range(_ctx(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PENDING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_cancels_provisioning_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING)
        cancel_range(_ctx(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_does_not_cancel_ready_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        cancel_range(_ctx(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.READY))
        range_obj.refresh_from_db()
        # READY is not cancellable; status is unchanged.
        assert range_obj.status == Range.Status.READY

    def test_cancel_missing_range_is_silent(self, user):
        # No row exists; cancel returns without raising.
        cancel_range(_ctx(range_id=999999, user_id=user.id, status=ResourceStatus.PENDING))
