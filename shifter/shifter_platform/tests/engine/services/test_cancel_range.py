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
from shared.schemas import InstanceSpec, RangeRef, RangeSpec, RequestSpec, SubnetSpec

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-cancel@example.com", email="engine-cancel@example.com")


def _ref(*, range_id, user_id, status=ResourceStatus.PENDING, request_id=None):
    return RangeRef(
        request_id=request_id or uuid4(),
        range_id=range_id,
        user_id=user_id,
        status=status,
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

    def test_rejects_non_rangeref(self):
        with pytest.raises(TypeError, match="must be RangeRef"):
            cancel_range("not-a-ref")

    def test_pydantic_rejects_negative_range_id(self):
        with pytest.raises(ValueError):
            RangeRef(
                request_id=uuid4(),
                range_id=-1,
                user_id=1,
                status=ResourceStatus.PENDING,
            )

    def test_cancels_provisioning_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_does_not_cancel_ready_range(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.READY))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    def test_ignores_stale_cancellable_ref_when_db_is_ready(self, user):
        """RangeRef.status is a snapshot; persisted Range.status is authoritative."""
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    def test_cancels_when_db_is_cancellable_despite_stale_ref_status(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.PROVISIONING)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.READY))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_missing_range_is_silent(self, user, caplog):
        with caplog.at_level(logging.WARNING, logger="engine"):
            result = cancel_range(_ref(range_id=999999, user_id=user.id, status=ResourceStatus.PENDING))

        assert result is None
        assert "range not found range_id=999999" in caplog.text

    def test_logs_cancellation(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.PENDING)
        with caplog.at_level(logging.INFO, logger="engine"):
            cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PENDING))
        assert "cancelled" in caplog.text.lower()
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_cancels_via_request_id_when_range_id_none(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        cancel_range(
            RangeRef(
                request_id=spec.request_id,
                range_id=None,
                user_id=user.id,
                status=ResourceStatus.PROVISIONING,
            )
        )
        range_obj = Range.objects.get(request__request_id=spec.request_id)
        assert range_obj.status == Range.Status.DESTROYING

    def test_raises_when_ids_missing_after_construct(self, user):
        ref = RangeRef.model_construct(
            request_id=None,
            range_id=None,
            user_id=user.id,
            status=ResourceStatus.PENDING,
        )
        with pytest.raises(ValueError, match="range_id or request_id"):
            cancel_range(ref)

    def test_raises_for_invalid_range_id_type(self, user):
        ref = RangeRef.model_construct(
            request_id=uuid4(),
            range_id="not-an-int",
            user_id=user.id,
            status=ResourceStatus.PENDING,
        )
        with pytest.raises(ValueError, match="non-negative integer"):
            cancel_range(ref)


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

    def test_returns_true_when_already_destroying(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYING)
        assert cancel_range_by_request(spec.request_id) is True

    def test_returns_false_when_request_not_found(self, db):
        assert cancel_range_by_request(uuid4()) is False
