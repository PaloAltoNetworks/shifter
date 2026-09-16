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
from django.utils import timezone

from engine import cancel_range, cancel_range_by_request
from engine.models import ProvisionerLaunchIntent, Range
from engine.models._launch import InterruptState
from engine.services import create_raes_range
from shared.enums import ResourceStatus
from shared.schemas import InstanceSpec, RangeRef, RangeSpec, RequestSpec, SubnetSpec

# Opaque #1325 workspace scope binding. engine.services requires one on every
# range create (ADR-046-R3); these suites do not exercise tenancy, so a fixed
# scalar stands in for the value the CMS launch facade would resolve.
_WORKSPACE_ID = 1

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


def create_range(spec, *, workspace_id):
    """Persist through the authoritative RAES engine seam."""
    return create_raes_range(
        request_id=spec.request_id,
        user_id=spec.user_id,
        compiled_plan={"kind": "raes_provisioning_plan", "raes_version": "2.0", "resources": {}},
        workspace_id=workspace_id,
    )


class TestCancelRange:
    def test_rejects_none(self):
        with pytest.raises(TypeError, match="cannot be None"):
            cancel_range(None)

    def test_rejects_non_rangeref(self):
        with pytest.raises(TypeError, match="must be RangeRef"):
            cancel_range("not-a-ref")

    def test_pydantic_rejects_negative_range_id(self):
        request_id = uuid4()
        with pytest.raises(ValueError):
            RangeRef(
                request_id=request_id,
                range_id=-1,
                user_id=1,
                status=ResourceStatus.PENDING,
            )

    def test_cancels_provisioning_range(self, user):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.PROVISIONING)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_does_not_cancel_ready_range(self, user):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.READY)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.READY))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    def test_ignores_stale_cancellable_ref_when_db_is_ready(self, user):
        """RangeRef.status is a snapshot; persisted Range.status is authoritative."""
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.READY)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    def test_cancels_when_db_is_cancellable_despite_stale_ref_status(self, user):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.PROVISIONING)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.READY))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_missing_range_is_silent(self, user, caplog):
        with caplog.at_level(logging.WARNING, logger="engine"):
            result = cancel_range(_ref(range_id=999999, user_id=user.id, status=ResourceStatus.PENDING))

        assert result is None
        assert "range not found range_id=999999" in caplog.text

    def test_logs_cancellation(self, user, caplog):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.PENDING)
        with caplog.at_level(logging.INFO, logger="engine"):
            cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PENDING))
        assert "cancelled" in caplog.text.lower()
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_cancels_via_request_id_when_range_id_none(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
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
        create_range(spec, workspace_id=_WORKSPACE_ID)  # persists a PROVISIONING Range + Request
        result = cancel_range_by_request(spec.request_id)
        assert result is True
        range_obj = Range.objects.get(request__request_id=spec.request_id)
        assert range_obj.status == Range.Status.DESTROYING

    def test_returns_false_for_non_cancellable_range(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.READY)
        assert cancel_range_by_request(spec.request_id) is False

    def test_returns_true_when_already_destroying(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYING)
        assert cancel_range_by_request(spec.request_id) is True

    def test_returns_false_when_request_not_found(self, db):
        assert cancel_range_by_request(uuid4()) is False


def _bind_raes_provision_intent(request_id):
    """Attach a current raes-range provision generation + launch intent to the range."""
    range_obj = Range.objects.get(request__request_id=request_id)
    op_id = uuid4()
    range_obj.provisioner_operation = "raes-range:provision"
    range_obj.provisioner_operation_id = op_id
    range_obj.save(update_fields=["provisioner_operation", "provisioner_operation_id"])
    return ProvisionerLaunchIntent.objects.create(
        operation_id=op_id,
        idempotency_key=f"idem-{op_id}",
        payload={"version": 1, "resource": "raes-range", "operation": "provision", "request_id": str(request_id)},
        next_attempt_at=timezone.now(),
    )


class TestCancelRecordsProvisionInterrupt:
    """Cancel records a durable interrupt bound to the current RAES provision generation.

    It marks the current provision launch intent for interruption but does NOT stop
    the task or enqueue a destroy inline -- the launcher worker converges those.
    """

    def test_cancel_by_request_records_interrupt(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        intent = _bind_raes_provision_intent(spec.request_id)

        assert cancel_range_by_request(spec.request_id) is True

        range_obj = Range.objects.get(request__request_id=spec.request_id)
        assert range_obj.status == Range.Status.DESTROYING
        intent.refresh_from_db()
        assert intent.interrupt_requested_at is not None
        assert intent.interrupt_state == InterruptState.REQUESTED
        assert intent.interrupt_next_attempt_at is not None
        assert intent.interrupt_deadline is not None
        # Cancel records intent only; it does not mint a destroy generation inline.
        assert ProvisionerLaunchIntent.objects.count() == 1

    def test_cancel_is_idempotent_on_repeat(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        intent = _bind_raes_provision_intent(spec.request_id)

        assert cancel_range_by_request(spec.request_id) is True
        intent.refresh_from_db()
        first_requested_at = intent.interrupt_requested_at

        assert cancel_range_by_request(spec.request_id) is True  # already DESTROYING
        intent.refresh_from_db()
        assert intent.interrupt_requested_at == first_requested_at
        assert intent.interrupt_state == InterruptState.REQUESTED

    def test_cancel_range_id_path_records_interrupt(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        intent = _bind_raes_provision_intent(spec.request_id)
        range_obj = Range.objects.get(request__request_id=spec.request_id)

        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING
        intent.refresh_from_db()
        assert intent.interrupt_state == InterruptState.REQUESTED

    def test_cancel_without_current_generation_is_plain_destroying(self, user):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.PROVISIONING)
        cancel_range(_ref(range_id=range_obj.id, user_id=user.id, status=ResourceStatus.PROVISIONING))
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING
        assert ProvisionerLaunchIntent.objects.count() == 0

    def test_cancel_does_not_interrupt_non_raes_generation(self, user):
        """AWS/legacy `range` generations are out of scope here (#1894): no interrupt recorded."""
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        range_obj = Range.objects.get(request__request_id=spec.request_id)
        op_id = uuid4()
        range_obj.provisioner_operation = "range:provision"
        range_obj.provisioner_operation_id = op_id
        range_obj.save(update_fields=["provisioner_operation", "provisioner_operation_id"])
        intent = ProvisionerLaunchIntent.objects.create(
            operation_id=op_id,
            idempotency_key=f"idem-{op_id}",
            payload={"version": 1, "resource": "range", "operation": "provision", "request_id": str(spec.request_id)},
            next_attempt_at=timezone.now(),
        )

        assert cancel_range_by_request(spec.request_id) is True

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING
        intent.refresh_from_db()
        assert intent.interrupt_requested_at is None
        assert intent.interrupt_state == InterruptState.NONE
