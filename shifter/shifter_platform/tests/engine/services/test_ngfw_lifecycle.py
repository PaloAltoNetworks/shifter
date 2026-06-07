"""Tests for engine.services start_ngfw / stop_ngfw lifecycle ops.

Mirrors the patching style of ``test_destroy_ngfw.py``.
"""

from __future__ import annotations

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from engine.models import Instance, Request
from engine.services import start_ngfw, stop_ngfw
from shared.enums import ResourceStatus


@pytest.fixture
def mock_request():
    request = Mock(spec=Request)
    request.request_id = uuid4()
    return request


def _ngfw(status):
    inst = Mock(spec=Instance)
    inst.id = 1
    inst.role = "ngfw"
    inst.status = status
    return inst


# ---------------------------------------------------------------------------
# start_ngfw
# ---------------------------------------------------------------------------


class TestStartNGFW:
    def test_returns_true_on_paused_ngfw(self, mock_request):
        ngfw = _ngfw(ResourceStatus.PAUSED.value)
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=ngfw))),
            patch("engine.ecs.start_ngfw_operation", return_value="arn:task/1") as op,
        ):
            assert start_ngfw(mock_request.request_id) is True
        op.assert_called_once_with(mock_request.request_id, "start")

    def test_returns_true_on_failed_ngfw(self, mock_request):
        ngfw = _ngfw(ResourceStatus.FAILED.value)
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=ngfw))),
            patch("engine.ecs.start_ngfw_operation", return_value="arn"),
        ):
            assert start_ngfw(mock_request.request_id) is True

    def test_returns_false_when_status_not_allowed(self, mock_request):
        ngfw = _ngfw(ResourceStatus.READY.value)
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=ngfw))),
            patch("engine.ecs.start_ngfw_operation") as op,
        ):
            assert start_ngfw(mock_request.request_id) is False
            op.assert_not_called()

    def test_returns_false_when_request_missing(self):
        rid = uuid4()
        with patch.object(Request.objects, "get", side_effect=Request.DoesNotExist):
            assert start_ngfw(rid) is False

    def test_returns_false_when_no_ngfw_instance(self, mock_request):
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=None))),
        ):
            assert start_ngfw(mock_request.request_id) is False

    def test_returns_false_when_task_arn_is_none(self, mock_request):
        ngfw = _ngfw(ResourceStatus.PAUSED.value)
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=ngfw))),
            patch("engine.ecs.start_ngfw_operation", return_value=None),
        ):
            assert start_ngfw(mock_request.request_id) is False


# ---------------------------------------------------------------------------
# stop_ngfw
# ---------------------------------------------------------------------------


class TestStopNGFW:
    def test_returns_true_on_ready_ngfw(self, mock_request):
        ngfw = _ngfw(ResourceStatus.READY.value)
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=ngfw))),
            patch("engine.ecs.start_ngfw_operation", return_value="arn:task/2") as op,
        ):
            assert stop_ngfw(mock_request.request_id) is True
        op.assert_called_once_with(mock_request.request_id, "stop")

    def test_returns_false_when_status_not_ready(self, mock_request):
        ngfw = _ngfw(ResourceStatus.PAUSED.value)
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=ngfw))),
            patch("engine.ecs.start_ngfw_operation") as op,
        ):
            assert stop_ngfw(mock_request.request_id) is False
            op.assert_not_called()

    def test_returns_false_when_request_missing(self):
        rid = uuid4()
        with patch.object(Request.objects, "get", side_effect=Request.DoesNotExist):
            assert stop_ngfw(rid) is False

    def test_returns_false_when_no_ngfw_instance(self, mock_request):
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=None))),
        ):
            assert stop_ngfw(mock_request.request_id) is False

    def test_returns_false_when_task_arn_is_none(self, mock_request):
        ngfw = _ngfw(ResourceStatus.READY.value)
        with (
            patch.object(Request.objects, "get", return_value=mock_request),
            patch.object(Instance.objects, "filter", return_value=Mock(first=Mock(return_value=ngfw))),
            patch("engine.ecs.start_ngfw_operation", return_value=None),
        ):
            assert stop_ngfw(mock_request.request_id) is False


# ---------------------------------------------------------------------------
# create_ngfw — validation branches
# ---------------------------------------------------------------------------


class TestCreateNGFWValidation:
    def test_raises_when_no_ngfw_instance_spec(self):
        from engine.services import create_ngfw
        from shared.schemas import RequestSpec

        # RequestSpec with no NGFW item
        spec = RequestSpec(request_id=uuid4(), user_id=1, items=[])
        with pytest.raises(ValueError, match="must contain an NGFW"):
            create_ngfw(spec)
