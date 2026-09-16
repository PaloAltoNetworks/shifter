"""Behavior tests for engine.services start_ngfw / stop_ngfw lifecycle ops.

Driven against real ``Request`` / ``Instance`` rows and the real ``engine.ecs``
operation dispatch with the ECS client mocked at the ``boto3`` boundary, instead
of patching ``Request.objects`` / ``Instance.objects`` / ``start_ngfw_operation``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import App, Instance, ProvisionerLaunchIntent, Request
from engine.services import create_ngfw, start_ngfw, stop_ngfw
from shared.enums import RequestType, ResourceStatus
from shared.schemas import InstanceSpec, NGFWAppSpec, RequestSpec

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-ngfwlife@example.com", email="engine-ngfwlife@example.com")


def _request(user):
    return Request.objects.create(request_id=uuid4(), request_type=RequestType.NGFW.value, user=user)


def _ngfw_for(request, status):
    return Instance.objects.create(
        uuid=uuid4(),
        request=request,
        role=Instance.Role.NGFW,
        os_type=Instance.OSType.PANOS,
        status=status,
        state={"management_ip": "10.1.5.10"},
    )


def _ngfw_request_spec(user_id):
    app_id = uuid4()
    instance_id = uuid4()
    return RequestSpec(
        request_id=uuid4(),
        user_id=user_id,
        items=[
            InstanceSpec(
                name="Edge NGFW",
                uuid=str(instance_id),
                role="ngfw",
                os_type="panos",
                ngfw_app=NGFWAppSpec(
                    name="Edge NGFW",
                    registration_method="otp",
                    app_id=app_id,
                    instance_id=instance_id,
                    user_id=user_id,
                    authcode="AUTH-XYZ",
                    otp_value="OTP123",
                    otp_folder="folder/",
                ),
            )
        ],
    )


class TestStartNGFW:
    @pytest.mark.parametrize("status", [ResourceStatus.PAUSED.value, ResourceStatus.FAILED.value])
    def test_returns_true_on_startable_status(self, user, ecs_dispatch, status):
        request = _request(user)
        _ngfw_for(request, status)
        assert start_ngfw(request.request_id) is True

    def test_dispatches_start_operation(self, user, ecs_dispatch):
        # Dispatch enqueues a ProvisionerLaunchIntent (#1833) instead of calling
        # boto3 run_task synchronously; the drainer submits the provider task.
        request = _request(user)
        _ngfw_for(request, ResourceStatus.PAUSED.value)
        assert start_ngfw(request.request_id) is True
        intent = ProvisionerLaunchIntent.objects.get()
        assert intent.payload["resource"] == "ngfw"
        assert intent.payload["operation"] == "start"
        assert intent.payload["request_id"] == str(request.request_id)
        ecs_dispatch.run_task.assert_not_called()

    def test_returns_false_when_status_not_allowed(self, user, ecs_dispatch):
        request = _request(user)
        _ngfw_for(request, ResourceStatus.READY.value)
        assert start_ngfw(request.request_id) is False
        ecs_dispatch.run_task.assert_not_called()

    def test_returns_false_when_request_missing(self, user):
        assert start_ngfw(uuid4()) is False

    def test_returns_false_when_no_ngfw_instance(self, user):
        request = _request(user)
        assert start_ngfw(request.request_id) is False

    def test_returns_false_when_task_arn_is_none(self, user, ecs_unconfigured):
        request = _request(user)
        _ngfw_for(request, ResourceStatus.PAUSED.value)
        assert start_ngfw(request.request_id) is False


class TestStopNGFW:
    def test_returns_true_on_ready_ngfw(self, user, ecs_dispatch):
        request = _request(user)
        _ngfw_for(request, ResourceStatus.READY.value)
        assert stop_ngfw(request.request_id) is True

    def test_dispatches_stop_operation(self, user, ecs_dispatch):
        # Dispatch enqueues a ProvisionerLaunchIntent (#1833) instead of calling
        # boto3 run_task synchronously; the drainer submits the provider task.
        request = _request(user)
        _ngfw_for(request, ResourceStatus.READY.value)
        assert stop_ngfw(request.request_id) is True
        intent = ProvisionerLaunchIntent.objects.get()
        assert intent.payload["resource"] == "ngfw"
        assert intent.payload["operation"] == "stop"
        assert intent.payload["request_id"] == str(request.request_id)
        ecs_dispatch.run_task.assert_not_called()

    def test_returns_false_when_status_not_ready(self, user, ecs_dispatch):
        request = _request(user)
        _ngfw_for(request, ResourceStatus.PAUSED.value)
        assert stop_ngfw(request.request_id) is False
        ecs_dispatch.run_task.assert_not_called()

    def test_returns_false_when_request_missing(self, user):
        assert stop_ngfw(uuid4()) is False

    def test_returns_false_when_no_ngfw_instance(self, user):
        request = _request(user)
        assert stop_ngfw(request.request_id) is False

    def test_returns_false_when_task_arn_is_none(self, user, ecs_unconfigured):
        request = _request(user)
        _ngfw_for(request, ResourceStatus.READY.value)
        assert stop_ngfw(request.request_id) is False


class TestCreateNGFWValidation:
    def test_raises_when_no_ngfw_instance_spec(self):
        from shared.schemas import RequestSpec

        spec = RequestSpec(request_id=uuid4(), user_id=1, items=[])
        with pytest.raises(ValueError, match="must contain an NGFW"):
            create_ngfw(spec)


class TestCreateNGFWPersistence:
    def test_marks_ngfw_rows_provisioning(self, user):
        spec = _ngfw_request_spec(user.id)
        assert create_ngfw(spec) == spec.request_id

        request = Request.objects.get(request_id=spec.request_id)
        ngfw_instance = Instance.objects.get(request=request, role=Instance.Role.NGFW)
        ngfw_app = App.objects.get(request=request, instance=ngfw_instance, app_type=App.AppType.NGFW)
        assert ngfw_instance.status == ResourceStatus.PROVISIONING.value
        assert ngfw_app.status == ResourceStatus.PROVISIONING.value

    def test_reuses_existing_ngfw_request(self, user):
        spec = _ngfw_request_spec(user.id)
        create_ngfw(spec)
        assert create_ngfw(spec) == spec.request_id
        assert Request.objects.filter(request_id=spec.request_id).count() == 1
        assert Instance.objects.filter(request__request_id=spec.request_id, role=Instance.Role.NGFW).count() == 1

    # The old synchronous "provider dispatch failed -> NGFW rows FAILED" path no
    # longer exists: dispatch enqueues a launch intent and the drainer owns
    # provider-dispatch failure (DLQ -> FAILED), covered by
    # tests/engine/test_provisioner_launch_outbox.py (ADR-043-R2, #1833).
