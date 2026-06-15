"""Behavior tests for destroy_range() / destroy_range_by_request() in engine/services.

Drives the real services against real ``Range`` rows: a destroyable range
transitions to DESTROYING and ECS teardown is dispatched (a no-op under the test
settings). Assertions are on the persisted status and the boolean result, not on
mocked ORM/ECS calls. The by-request variant resolves the range via its linked
Request, set up by calling the real ``create_range``.
"""

import logging
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine import create_range, destroy_range, destroy_range_by_request
from engine.models import Range
from shared.enums import ResourceStatus
from shared.schemas import InstanceSpec, RangeContext, RangeSpec, RequestSpec, SubnetSpec

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-destroy@example.com", email="engine-destroy@example.com")


def _ctx(*, range_id, user_id):
    return RangeContext(
        request_id=uuid4(),
        range_id=range_id,
        user_id=user_id,
        scenario_id="s",
        status=ResourceStatus.READY,
        instances=[],
    )


def _request_spec(user_id):
    return RequestSpec(
        request_id=uuid4(),
        user_id=user_id,
        items=[
            RangeSpec(
                uuid=str(uuid4()),
                scenario_id="basic",
                user_id=user_id,
                subnets=[
                    SubnetSpec(
                        name="default",
                        uuid=str(uuid4()),
                        instances=[InstanceSpec(role="attacker", os_type="kali", uuid=str(uuid4()))],
                        connected_to=[],
                    )
                ],
            )
        ],
    )


class TestDestroyRange:
    def test_destroyable_range_returns_true_and_sets_destroying(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        assert destroy_range(_ctx(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_idempotent_when_already_destroying(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.DESTROYING)
        assert destroy_range(_ctx(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_returns_false_when_already_destroyed(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.DESTROYED)
        assert destroy_range(_ctx(range_id=range_obj.id, user_id=user.id)) is False

    def test_returns_false_when_not_found(self, user):
        assert destroy_range(_ctx(range_id=999999, user_id=user.id)) is False

    def test_logs_status_change(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        with caplog.at_level(logging.INFO, logger="engine"):
            destroy_range(_ctx(range_id=range_obj.id, user_id=user.id))
        assert "DESTROYING" in caplog.text

    def test_logs_warning_when_not_found(self, user, caplog):
        with caplog.at_level(logging.WARNING, logger="engine"):
            destroy_range(_ctx(range_id=999999, user_id=user.id))
        assert "not found" in caplog.text.lower()


class TestDestroyRangeByRequest:
    def test_returns_true_and_sets_destroying(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        assert destroy_range_by_request(spec.request_id) is True
        assert Range.objects.get(request__request_id=spec.request_id).status == Range.Status.DESTROYING

    def test_idempotent_for_already_destroying(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYING)
        assert destroy_range_by_request(spec.request_id) is True

    def test_returns_false_when_already_destroyed(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYED)
        assert destroy_range_by_request(spec.request_id) is False

    def test_returns_false_when_request_not_found(self, db):
        assert destroy_range_by_request(uuid4()) is False
