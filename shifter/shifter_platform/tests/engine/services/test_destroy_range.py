"""Behavior tests for destroy_range() / destroy_range_by_request() in engine/services.

Drives the real services against real ``Range`` rows: a destroyable range
transitions to DESTROYING and ECS teardown is dispatched (a no-op under the test
settings). Assertions are on the persisted status and the boolean result, not on
mocked ORM/ECS calls. The by-request variant resolves the range via its linked
Request, set up by calling the real ``create_range``.
"""

import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine import create_range, destroy_range, destroy_range_by_request
from engine.models import Range
from shared.cloud.exceptions import CloudTaskError
from shared.enums import ResourceStatus
from shared.schemas import InstanceSpec, RangeRef, RangeSpec, RequestSpec, SubnetSpec

from .conftest import ECS_TASK_ARN

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


class TestDestroyRange:
    def test_rejects_non_rangeref(self):
        with pytest.raises(TypeError, match="must be RangeRef"):
            destroy_range("not-a-ref")

    def test_destroyable_range_returns_true_and_sets_destroying(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_destroy_sets_teardown_arn_without_overwriting_provisioning(self, user, ecs_dispatch):
        spec = _request_spec(user.id)
        create_range(spec)
        range_obj = Range.objects.get()
        Range.objects.filter(id=range_obj.id).update(status=Range.Status.READY)
        provisioning_arn = range_obj.provisioning_task_arn
        assert provisioning_arn == ECS_TASK_ARN

        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        assert range_obj.provisioning_task_arn == provisioning_arn
        assert range_obj.teardown_task_arn == ECS_TASK_ARN

    def test_reverts_status_when_teardown_dispatch_fails(self, user, settings):
        settings.CLOUD_PROVIDER = "aws"
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
        ecs_client = MagicMock()
        ecs_client.run_task.return_value = {"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]}
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)

        with patch("boto3.client", return_value=ecs_client), pytest.raises(CloudTaskError):
            destroy_range(_ref(range_id=range_obj.id, user_id=user.id))

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    def test_idempotent_when_already_destroying(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.DESTROYING)
        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is True
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYING

    def test_returns_false_when_already_destroyed(self, user):
        range_obj = Range.objects.create(user=user, status=Range.Status.DESTROYED)
        assert destroy_range(_ref(range_id=range_obj.id, user_id=user.id)) is False

    def test_returns_false_when_not_found(self, user):
        assert destroy_range(_ref(range_id=999999, user_id=user.id)) is False

    def test_destroys_via_request_id_when_range_id_none(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        ref = RangeRef(
            request_id=spec.request_id,
            range_id=None,
            user_id=user.id,
            status=ResourceStatus.PROVISIONING,
        )
        assert destroy_range(ref) is True
        assert Range.objects.get(request__request_id=spec.request_id).status == Range.Status.DESTROYING

    def test_logs_status_change(self, user, caplog):
        range_obj = Range.objects.create(user=user, status=Range.Status.READY)
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
        create_range(spec)
        assert destroy_range_by_request(spec.request_id) is True
        assert Range.objects.get(request__request_id=spec.request_id).status == Range.Status.DESTROYING

    def test_destroy_by_request_sets_teardown_without_overwriting_provisioning(self, user, ecs_dispatch):
        spec = _request_spec(user.id)
        create_range(spec)
        range_obj = Range.objects.get(request__request_id=spec.request_id)
        Range.objects.filter(id=range_obj.id).update(status=Range.Status.READY)
        provisioning_arn = range_obj.provisioning_task_arn
        assert provisioning_arn == ECS_TASK_ARN

        assert destroy_range_by_request(spec.request_id) is True
        range_obj.refresh_from_db()
        assert range_obj.provisioning_task_arn == provisioning_arn
        assert range_obj.teardown_task_arn == ECS_TASK_ARN

    def test_reverts_status_when_teardown_dispatch_fails(self, user, settings):
        settings.CLOUD_PROVIDER = "aws"
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = ""
        settings.ENGINE_TASK_DEFINITION = ""
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = ""
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = ""
        spec = _request_spec(user.id)
        create_range(spec)
        range_obj = Range.objects.get(request__request_id=spec.request_id)
        Range.objects.filter(id=range_obj.id).update(status=Range.Status.READY)

        settings.CLOUD_PROVIDER = "aws"
        settings.LOCAL_PROVISIONER = None
        settings.ENGINE_TASK_CLUSTER = "test-cluster"
        settings.ENGINE_TASK_DEFINITION = "test-taskdef"
        settings.ENGINE_TASK_NETWORK_SECURITY_GROUP_ID = "sg-test"
        settings.ENGINE_TASK_NETWORK_SUBNET_IDS = "subnet-aaa,subnet-bbb"
        ecs_client = MagicMock()
        ecs_client.run_task.return_value = {"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]}

        with patch("boto3.client", return_value=ecs_client), pytest.raises(CloudTaskError):
            destroy_range_by_request(spec.request_id)

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    def test_idempotent_for_already_destroying(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYING)
        assert destroy_range_by_request(spec.request_id) is True
        assert Range.objects.get(request__request_id=spec.request_id).status == Range.Status.DESTROYING

    def test_returns_false_when_already_destroyed(self, user):
        spec = _request_spec(user.id)
        create_range(spec)
        Range.objects.filter(request__request_id=spec.request_id).update(status=Range.Status.DESTROYED)
        assert destroy_range_by_request(spec.request_id) is False

    def test_returns_false_when_request_not_found(self, db):
        assert destroy_range_by_request(uuid4()) is False
