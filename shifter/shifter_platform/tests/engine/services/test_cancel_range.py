"""Behavior tests for cancel_range() / cancel_range_by_request() in engine/services.

Drives the real services against real ``Range`` rows. cancel_range transitions a
cancellable range (PENDING/PROVISIONING per the supplied context) to DESTROYING;
the by-request variant resolves the range via its linked Request. ``create_range``
is used to set up the by-request fixtures (it persists a Range + Request).
"""

import logging
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine import cancel_range, cancel_range_by_request, create_range
from engine.models import Range
from shared.enums import ResourceStatus
from shared.schemas import InstanceSpec, RangeContext, RangeSpec, RequestSpec, SubnetSpec

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-cancel@example.com", email="engine-cancel@example.com")


def _ctx(*, range_id, user_id, status=ResourceStatus.PENDING):
    return RangeContext(
        request_id=uuid4(), range_id=range_id, user_id=user_id, scenario_id="s", status=status, instances=[]
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


class TestCancelRange:
    def test_rejects_none(self):
        with pytest.raises(TypeError, match="cannot be None"):
            cancel_range(None)

    def test_rejects_non_rangecontext(self):
        with pytest.raises(TypeError, match="must be RangeContext"):
            cancel_range("not-a-context")

    def test_pydantic_rejects_negative_range_id(self):
        with pytest.raises(ValueError):
            RangeContext(
                request_id=uuid4(), range_id=-1, user_id=1, scenario_id="s", status=ResourceStatus.PENDING, instances=[]
            )

    def test_cancels_provisioning_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING)
        cancel_range(_ctx(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_does_not_cancel_ready_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        cancel_range(_ctx(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.READY))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    def test_missing_range_is_silent(self, user):
        cancel_range(_ctx(range_id=999999, user_id=user.id, status=ResourceStatus.PENDING))

    def test_logs_cancellation(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        with caplog.at_level(logging.INFO, logger="engine"):
            cancel_range(_ctx(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PENDING))
        assert "cancelled" in caplog.text.lower()


class TestCancelRangeByRequest:
    def test_returns_true_and_destroys_cancellable_range(self, user):
        spec = _request_spec(user.id)
        create_range(spec)  # persists a PROVISIONING Range + Request
        result = cancel_range_by_request(spec.request_id)
        assert result is True
        range_obj = Range.objects.get(request__request_id=spec.request_id)
        assert range_obj.status == Range.Status.DESTROYING

    def test_returns_false_for_non_cancellable_range(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.READY)
        assert cancel_range_by_request(spec.request_id) is False

    def test_returns_false_when_request_not_found(self, db):
        assert cancel_range_by_request(uuid4()) is False
