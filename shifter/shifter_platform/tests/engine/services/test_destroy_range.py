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

from engine import destroy_range, destroy_range_by_request
from engine.models import ProvisionerLaunchIntent, Range
from engine.services import create_raes_range
from shared.enums import ResourceStatus
from shared.raes.runtime_target import RAES_PROVISIONING_PLAN_KIND
from shared.schemas import InstanceSpec, RangeRef, RangeSpec, RequestSpec, SubnetSpec

# Opaque #1325 workspace scope binding. engine.services requires one on every
# range create (ADR-046-R3); these suites do not exercise tenancy, so a fixed
# scalar stands in for the value the CMS launch facade would resolve.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-destroy@example.com", email="engine-destroy@example.com")


def _ref(*, range_id, user_id, request_id=None, status=ResourceStatus.READY):
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
        compiled_plan={"kind": RAES_PROVISIONING_PLAN_KIND, "raes_version": "2.0", "resources": {}},
        workspace_id=workspace_id,
    )


class TestDestroyRange:
    def test_rejects_non_rangeref(self):
        with pytest.raises(TypeError, match="must be RangeRef"):
            destroy_range("not-a-ref")

    def test_destroyable_range_returns_true_and_sets_destroying(self, user):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.READY)
        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_destroy_sets_teardown_arn_without_overwriting_provisioning(self, user, ecs_dispatch):
        # Dispatch enqueues a ProvisionerLaunchIntent per operation (#1833);
        # destroy records the teardown intent's launch ref without touching the
        # provisioning intent's ref, and nothing reaches the boto3 ECS boundary.
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        range_obj = Range.objects.get()
        Range.objects.filter(id=range_obj.id).update(status=Range.Status.READY)
        range_obj.refresh_from_db()
        provisioning_arn = range_obj.provisioning_task_arn
        assert provisioning_arn.startswith("test-cluster/pulumi-provisioner-")
        provisioning_intent = ProvisionerLaunchIntent.objects.get()

        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        teardown_intent = ProvisionerLaunchIntent.objects.exclude(pk=provisioning_intent.pk).get()
        assert range_obj.provisioning_task_arn == provisioning_arn
        assert range_obj.teardown_task_arn == teardown_intent.task_ref
        assert range_obj.teardown_task_arn.startswith("test-cluster/pulumi-provisioner-")
        ecs_dispatch.run_task.assert_not_called()

    # The old synchronous "provider dispatch failed -> range reverted" path no
    # longer exists: dispatch enqueues a launch intent and the drainer owns
    # provider-dispatch failure (DLQ -> FAILED), covered by
    # tests/engine/test_provisioner_launch_outbox.py (ADR-043-R2, #1833).

    def test_idempotent_when_already_destroying(self, user):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.DESTROYING)
        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_returns_false_when_already_destroyed(self, user):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.DESTROYED)
        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is False

    def test_returns_false_when_not_found(self, user):
        assert destroy_range(_ref(range_id=999999, user_id=user.id)) is False

    def test_destroys_via_request_id_when_range_id_none(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        ref = RangeRef(
            request_id=spec.request_id,
            range_id=None,
            user_id=user.id,
            status=ResourceStatus.PROVISIONING,
        )
        assert destroy_range(ref) is True
        assert Range.objects.get(request__request_id=spec.request_id).status == Range.Status.DESTROYING

    def test_logs_status_change(self, user, caplog):
        range_obj = Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=Range.Status.READY)
        with caplog.at_level(logging.INFO, logger="engine"):
            destroy_range(_ref(range_id=range_obj.id, user_id=user.id))
        assert "DESTROYING" in caplog.text
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_logs_warning_when_not_found(self, user, caplog):
        with caplog.at_level(logging.WARNING, logger="engine"):
            destroy_range(_ref(range_id=999999, user_id=user.id))
        assert "not found" in caplog.text.lower()


class TestDestroyRangeByRequest:
    def test_returns_true_and_sets_destroying(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        assert destroy_range_by_request(spec.request_id) is True
        assert Range.objects.get(request__request_id=spec.request_id).status == Range.Status.DESTROYING

    def test_destroy_by_request_sets_teardown_without_overwriting_provisioning(self, user, ecs_dispatch):
        # Dispatch enqueues a ProvisionerLaunchIntent per operation (#1833);
        # destroy records the teardown intent's launch ref without touching the
        # provisioning intent's ref, and nothing reaches the boto3 ECS boundary.
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        range_obj = Range.objects.get(request__request_id=spec.request_id)
        Range.objects.filter(id=range_obj.id).update(status=Range.Status.READY)
        range_obj.refresh_from_db()
        provisioning_arn = range_obj.provisioning_task_arn
        assert provisioning_arn.startswith("test-cluster/pulumi-provisioner-")
        provisioning_intent = ProvisionerLaunchIntent.objects.get()

        assert destroy_range_by_request(spec.request_id) is True
        range_obj.refresh_from_db()
        teardown_intent = ProvisionerLaunchIntent.objects.exclude(pk=provisioning_intent.pk).get()
        assert range_obj.provisioning_task_arn == provisioning_arn
        assert range_obj.teardown_task_arn == teardown_intent.task_ref
        assert range_obj.teardown_task_arn.startswith("test-cluster/pulumi-provisioner-")
        ecs_dispatch.run_task.assert_not_called()

    # The old synchronous "provider dispatch failed -> range reverted" path no
    # longer exists: dispatch enqueues a launch intent and the drainer owns
    # provider-dispatch failure (DLQ -> FAILED), covered by
    # tests/engine/test_provisioner_launch_outbox.py (ADR-043-R2, #1833).

    def test_idempotent_for_already_destroying(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYING)
        assert destroy_range_by_request(spec.request_id) is True
        assert Range.objects.get(request__request_id=spec.request_id).status == Range.Status.DESTROYING

    def test_returns_false_when_already_destroyed(self, user):
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYED)
        assert destroy_range_by_request(spec.request_id) is False

    def test_returns_false_when_request_not_found(self, db):
        assert destroy_range_by_request(uuid4()) is False

    def test_raes_range_enqueues_raes_teardown(self, user, ecs_dispatch):
        """A persisted RAES plan enqueues the 'raes-range destroy' intent, not legacy (#1310)."""
        spec = _request_spec(user.id)
        create_range(spec, workspace_id=_WORKSPACE_ID)
        provision_intent = ProvisionerLaunchIntent.objects.get()
        Range.objects.filter(request__request_id=spec.request_id).update(
            range_config={"kind": RAES_PROVISIONING_PLAN_KIND, "contract_version": "1", "resources": {}}
        )
        assert destroy_range_by_request(spec.request_id) is True
        teardown = ProvisionerLaunchIntent.objects.exclude(pk=provision_intent.pk).get()
        assert teardown.payload["resource"] == "raes-range"
        assert teardown.payload["operation"] == "destroy"
