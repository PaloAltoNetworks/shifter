"""Behavior tests for destroy_ngfw() in engine/services.

Driven against real ``Request`` / ``Instance`` / ``Range`` rows (the service uses
normal queries) and the real ``engine.ecs`` teardown dispatch with the ECS client
mocked at the ``boto3`` boundary, instead of patching ``Request.objects`` /
``Instance.objects`` / ``Range.objects`` / ``start_ngfw_teardown``.
"""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import Instance, Range, Request
from engine.services import EngineError, destroy_ngfw
from shared.enums import RequestType, ResourceStatus

from .conftest import ecs_run_task_command

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-destroyngfw@example.com", email="engine-destroyngfw@example.com")


def _request(user):
    return Request.objects.create(request_id=uuid4(), request_type=RequestType.NGFW.value, user=user)


def _ngfw_for(request):
    return Instance.objects.create(
        uuid=uuid4(),
        request=request,
        role=Instance.Role.NGFW,
        os_type=Instance.OSType.PANOS,
        status=ResourceStatus.READY.value,
        state={"management_ip": "10.1.5.10"},
    )


def _attach_range(user, ngfw, *, status):
    return Range.objects.create(user=user, status=status, ngfw_instance=ngfw)


class TestDestroyNGFW:
    def test_returns_true_when_ngfw_found_and_no_attached_ranges(self, user, ecs_dispatch):
        request = _request(user)
        _ngfw_for(request)
        assert destroy_ngfw(request.request_id) is True

    def test_returns_false_when_request_not_found(self, user):
        assert destroy_ngfw(uuid4()) is False

    def test_returns_false_when_ngfw_instance_not_found(self, user):
        request = _request(user)  # request exists but no NGFW instance
        assert destroy_ngfw(request.request_id) is False

    def test_raises_engine_error_when_ranges_attached(self, user, ecs_dispatch):
        request = _request(user)
        ngfw = _ngfw_for(request)
        _attach_range(user, ngfw, status=Range.Status.READY)
        _attach_range(user, ngfw, status=Range.Status.PROVISIONING)
        with pytest.raises(EngineError) as exc_info:
            destroy_ngfw(request.request_id)
        message = str(exc_info.value)
        assert "Cannot delete NGFW" in message
        assert "2 range(s)" in message

    def test_error_message_includes_range_ids(self, user, ecs_dispatch):
        request = _request(user)
        ngfw = _ngfw_for(request)
        attached = _attach_range(user, ngfw, status=Range.Status.READY)
        with pytest.raises(EngineError) as exc_info:
            destroy_ngfw(request.request_id)
        assert str(attached.id) in str(exc_info.value)

    def test_inactive_attached_ranges_do_not_block(self, user, ecs_dispatch):
        # Only active-status ranges block deletion; destroyed/failed ones don't.
        request = _request(user)
        ngfw = _ngfw_for(request)
        _attach_range(user, ngfw, status=Range.Status.DESTROYED)
        _attach_range(user, ngfw, status=Range.Status.FAILED)
        assert destroy_ngfw(request.request_id) is True

    def test_dispatches_teardown_with_request_id(self, user, ecs_dispatch):
        request = _request(user)
        _ngfw_for(request)
        destroy_ngfw(request.request_id)
        assert ecs_run_task_command(ecs_dispatch) == ["ngfw", "deprovision", "--request-id", str(request.request_id)]

    def test_returns_false_when_teardown_returns_none(self, user, ecs_unconfigured):
        # ECS unconfigured -> start_ngfw_teardown returns None -> destroy returns False.
        request = _request(user)
        _ngfw_for(request)
        assert destroy_ngfw(request.request_id) is False
