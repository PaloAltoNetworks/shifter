"""Behavior tests for resume_range() in engine/services.

Drives the real service against real ``Range`` rows resolved via their linked
Request (set up with the real ``create_range``). A PAUSED range transitions to
RESUMING and a no-op ECS operation is dispatched under the test settings; other
statuses are rejected, and READY/RESUMING are idempotent.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from engine import create_range, resume_range
from engine.models import Range
from shared.schemas import InstanceSpec, RangeSpec, RequestSpec, SubnetSpec

pytestmark = pytest.mark.django_db

User = get_user_model()

# See test_pause_range: ECS is configured so the op can dispatch, with the AWS
# task runner mocked at the boto3 boundary to return a task ARN.
ECS_SETTINGS = {
    "CLOUD_PROVIDER": "aws",
    "ENGINE_TASK_CLUSTER": "test-cluster",
    "ENGINE_TASK_DEFINITION": "test-taskdef",
    "ENGINE_TASK_NETWORK_SECURITY_GROUP_ID": "sg-test",
    "ENGINE_TASK_NETWORK_SUBNET_IDS": "subnet-aaa,subnet-bbb",
}


def _ecs_client_mock():
    client = MagicMock()
    client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-2:123:task/cluster/op"}]}
    return client


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-resume@example.com", email="engine-resume@example.com")


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


@pytest.fixture
def request_id_in_status(user):
    def _make(status):
        spec = _request_spec(user.id)
        create_range(spec)
        Range.objects.filter(request__request_id=spec.request_id).update(status=status)
        return spec.request_id

    return _make


class TestResumeRange:
    def test_resumes_a_paused_range(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.PAUSED)
        # Configure ECS + mock the boto3 dispatch only around the resume call, so
        # the create_range setup above still runs with ECS as a no-op.
        with override_settings(**ECS_SETTINGS), patch("boto3.client", return_value=_ecs_client_mock()):
            assert resume_range(request_id) is True
        assert Range.objects.get(request__request_id=request_id).status == Range.Status.RESUMING

    def test_idempotent_when_already_ready(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.READY)
        assert resume_range(request_id) is True
        assert Range.objects.get(request__request_id=request_id).status == Range.Status.READY

    def test_idempotent_when_already_resuming(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.RESUMING)
        assert resume_range(request_id) is True

    def test_rejects_non_paused_range(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.PROVISIONING)
        assert resume_range(request_id) is False
        assert Range.objects.get(request__request_id=request_id).status == Range.Status.PROVISIONING

    def test_returns_false_when_request_not_found(self, db):
        assert resume_range(uuid4()) is False
