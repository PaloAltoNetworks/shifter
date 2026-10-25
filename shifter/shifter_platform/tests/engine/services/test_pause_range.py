"""Behavior tests for pause_range() in engine/services.

Drives the real service against real ``Range`` rows resolved via their linked
Request with a legacy instance-inventory configuration. A READY range transitions to
PAUSING and a no-op ECS operation is dispatched under the test settings; other
statuses are rejected, and PAUSED/PAUSING are idempotent.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from engine import pause_range
from engine.models import Range, Request

# Opaque #1325 workspace scope binding. engine.services requires one on every
# range create (ADR-046-R3); these suites do not exercise tenancy, so a fixed
# scalar stands in for the value the CMS launch facade would resolve.
_WORKSPACE_ID = 1

pytestmark = pytest.mark.django_db

User = get_user_model()

# Configure ECS so the lifecycle op can dispatch a task; the AWS task runner is
# mocked at the boto3 boundary to return a task ARN (a successful dispatch is
# what lets pause/resume complete instead of reverting).
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
    return User.objects.create_user(username="engine-pause@example.com", email="engine-pause@example.com")


@pytest.fixture
def request_id_in_status(user):
    """Persist the legacy Range+Request consumed by the power worker."""

    def _make(status):
        request = Request.objects.create(request_id=uuid4(), request_type="range", user=user)
        Range.objects.create(request=request, user=user, workspace_id=_WORKSPACE_ID, range_config={}, status=status)
        return request.request_id

    return _make


class TestPauseRange:
    def test_pauses_a_ready_range(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.READY)
        # Configure ECS + mock the boto3 dispatch only around the pause call, so
        # the persisted fixture requires no cloud provisioning.
        with override_settings(**ECS_SETTINGS), patch("boto3.client", return_value=_ecs_client_mock()):
            assert pause_range(request_id) is True
        assert Range.objects.get(request__request_id=request_id).status == Range.Status.PAUSING

    def test_idempotent_when_already_paused(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.PAUSED)
        assert pause_range(request_id) is True
        assert Range.objects.get(request__request_id=request_id).status == Range.Status.PAUSED

    def test_idempotent_when_already_pausing(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.PAUSING)
        assert pause_range(request_id) is True

    def test_rejects_non_ready_range(self, request_id_in_status):
        request_id = request_id_in_status(Range.Status.PROVISIONING)
        assert pause_range(request_id) is False
        assert Range.objects.get(request__request_id=request_id).status == Range.Status.PROVISIONING

    def test_returns_false_when_request_not_found(self, db):
        assert pause_range(uuid4()) is False
