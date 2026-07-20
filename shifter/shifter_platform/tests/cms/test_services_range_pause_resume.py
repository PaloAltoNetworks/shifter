"""Behavior tests for CMS pause_range / resume_range services.

Drives the real services against a real provisioned range. CMS delegates to the
engine pause/resume ops, which only succeed when the engine Range is in the right
status and ECS is configured; ECS is mocked at the ``boto3`` boundary. When the
engine op cannot run, CMS reverts the status and raises CMSError. No first-party
patching of ``RangeInstance.objects`` / the engine calls / ``audit_log``.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from cms import services
from cms.exceptions import CMSError
from cms.models import RangeInstance
from engine.models import Range as EngineRange
from shared.enums import ResourceStatus

pytestmark = pytest.mark.django_db

User = get_user_model()

# ECS configured so the engine op can dispatch, with the AWS task runner mocked
# at the boto3 boundary to return a task ARN.
ECS_SETTINGS = {
    "CLOUD_PROVIDER": "aws",
    "LOCAL_PROVISIONER": None,
    "ENGINE_TASK_CLUSTER": "test-cluster",
    "ENGINE_TASK_DEFINITION": "test-taskdef",
    "ENGINE_TASK_NETWORK_SECURITY_GROUP_ID": "sg-test",
    "ENGINE_TASK_NETWORK_SUBNET_IDS": "subnet-aaa,subnet-bbb",
}


def _ecs_client():
    client = MagicMock()
    client.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:us-east-2:123:task/cluster/op"}]}
    return client


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cms-pause@example.com", email="cms-pause@example.com")


def _request_id_of(range_instance):
    return str(range_instance.request.request_id)


class TestPauseRange:
    def test_pauses_a_ready_range(self, user, provision_range):
        # range_id deliberately differs from pk to prove the lifecycle path
        # resolves by RangeInstance PK, not the engine range_id field (#1139).
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.READY)
        with override_settings(**ECS_SETTINGS), patch("boto3.client", return_value=_ecs_client()):
            services.pause_range(user, ri.pk)
        assert RangeInstance.objects.get(pk=ri.pk).status == ResourceStatus.PAUSING.value

    def test_reverts_and_raises_when_engine_rejects(self, user, provision_range):
        # Engine Range is PROVISIONING (not pausable) -> engine pause returns
        # False -> CMS reverts to READY and raises.
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.PROVISIONING)
        with pytest.raises(CMSError, match="cannot be paused"):
            services.pause_range(user, ri.pk)
        assert RangeInstance.objects.get(pk=ri.pk).status == ResourceStatus.READY.value

    def test_raises_cms_error_when_range_not_found(self, user):
        with pytest.raises(CMSError, match="not found"):
            services.pause_range(user, 999999)

    def test_raises_cms_error_when_not_owner(self, user, django_user_model, provision_range):
        other = django_user_model.objects.create_user(username="cms-p-other@e.com", email="cms-p-other@e.com")
        ri = provision_range(other, range_id=55, engine_status=EngineRange.Status.READY)
        with pytest.raises(CMSError, match="not found"):
            services.pause_range(user, ri.pk)


class TestResumeRange:
    def test_resumes_a_paused_range(self, user, provision_range):
        # range_id deliberately differs from pk (see #1139).
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.PAUSED)
        with override_settings(**ECS_SETTINGS), patch("boto3.client", return_value=_ecs_client()):
            services.resume_range(user, ri.pk)
        assert RangeInstance.objects.get(pk=ri.pk).status == ResourceStatus.RESUMING.value

    def test_reverts_and_raises_when_engine_rejects(self, user, provision_range):
        # Engine Range is PROVISIONING (not resumable) -> engine resume returns
        # False -> CMS reverts to PAUSED and raises.
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.PROVISIONING)
        with pytest.raises(CMSError, match="cannot be resumed"):
            services.resume_range(user, ri.pk)
        assert RangeInstance.objects.get(pk=ri.pk).status == ResourceStatus.PAUSED.value

    def test_raises_cms_error_when_range_not_found(self, user):
        with pytest.raises(CMSError, match="not found"):
            services.resume_range(user, 999999)

    def test_raises_cms_error_when_not_owner(self, user, django_user_model, provision_range):
        other = django_user_model.objects.create_user(username="cms-r-other@e.com", email="cms-r-other@e.com")
        ri = provision_range(other, range_id=66, engine_status=EngineRange.Status.PAUSED)
        with pytest.raises(CMSError, match="not found"):
            services.resume_range(user, ri.pk)


class TestLifecycleResolvesByPk:
    """Regression for #1139.

    CTF stores ``RangeInstance.pk`` (``find_range_instance_id_by_request`` is
    PK-keyed) and the lifecycle bridges pass it straight through. The lifecycle
    ops must therefore resolve by PK, never the legacy nullable ``range_id``
    engine field. Here ``range_id`` is set far from the small auto PK so the two
    can never coincide.
    """

    def test_pause_resolves_by_pk_not_range_id_field(self, user, provision_range):
        ri = provision_range(user, range_id=999_999, engine_status=EngineRange.Status.READY)
        assert ri.pk != ri.range_id
        # Passing the engine range_id value must NOT resolve the instance.
        with pytest.raises(CMSError, match="not found"):
            services.pause_range(user, ri.range_id)
        # Passing the PK resolves and pauses it.
        with override_settings(**ECS_SETTINGS), patch("boto3.client", return_value=_ecs_client()):
            services.pause_range(user, ri.pk)
        assert RangeInstance.objects.get(pk=ri.pk).status == ResourceStatus.PAUSING.value


class TestPauseRangeByRequestId:
    def test_pauses_a_ready_range(self, user, provision_range):
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.READY)
        with override_settings(**ECS_SETTINGS), patch("boto3.client", return_value=_ecs_client()):
            services.pause_range_by_request_id(user, _request_id_of(ri))
        assert RangeInstance.objects.get(range_id=42).status == ResourceStatus.PAUSING.value

    def test_reverts_when_engine_rejects(self, user, provision_range):
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.PROVISIONING)
        with pytest.raises(CMSError):
            services.pause_range_by_request_id(user, _request_id_of(ri))
        assert RangeInstance.objects.get(range_id=42).status == ResourceStatus.READY.value

    def test_raises_cms_error_when_not_found(self, user):
        from uuid import uuid4

        with pytest.raises(CMSError):
            services.pause_range_by_request_id(user, str(uuid4()))


class TestResumeRangeByRequestId:
    def test_resumes_a_paused_range(self, user, provision_range):
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.PAUSED)
        with override_settings(**ECS_SETTINGS), patch("boto3.client", return_value=_ecs_client()):
            services.resume_range_by_request_id(user, _request_id_of(ri))
        assert RangeInstance.objects.get(range_id=42).status == ResourceStatus.RESUMING.value

    def test_reverts_when_engine_rejects(self, user, provision_range):
        ri = provision_range(user, range_id=42, engine_status=EngineRange.Status.PROVISIONING)
        with pytest.raises(CMSError):
            services.resume_range_by_request_id(user, _request_id_of(ri))
        assert RangeInstance.objects.get(range_id=42).status == ResourceStatus.PAUSED.value

    def test_raises_cms_error_when_not_found(self, user):
        from uuid import uuid4

        with pytest.raises(CMSError):
            services.resume_range_by_request_id(user, str(uuid4()))
