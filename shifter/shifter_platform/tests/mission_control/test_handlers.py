"""Behavior tests for Mission Control SNS->WebSocket handlers.

Drives the handlers against the real in-memory Django Channels layer: a test
channel subscribes to the expected group, the handler runs, and the broadcast
is received and asserted. The channel layer is the real external transport
boundary, so nothing first-party is patched.
"""

import asyncio
import json
from uuid import uuid4

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from mission_control.handlers import (
    EVENT_TYPE_NGFW,
    parse_sns_message,
    process_event,
    process_ngfw_event,
    process_range_event,
)
from shared.channels.groups import ngfw_event_group, range_event_group
from shared.enums import ResourceStatus


def _sns(payload):
    return {"Message": json.dumps(payload)}


@pytest.fixture(autouse=True)
def _flush_channel_layer():
    layer = get_channel_layer()
    async_to_sync(layer.flush)()
    yield
    async_to_sync(layer.flush)()


def _subscribe(group):
    layer = get_channel_layer()
    channel = f"recv-{uuid4()}"
    async_to_sync(layer.group_add)(group, channel)
    return layer, channel


def _receive(layer, channel, timeout=0.2):
    async def _r():
        try:
            return await asyncio.wait_for(layer.receive(channel), timeout)
        except TimeoutError:
            return None

    return async_to_sync(_r)()


class TestParseSnsMessage:
    def test_unwraps_sns_envelope(self):
        result = parse_sns_message(_sns({"event_type": "range.status.updated", "range_id": 1, "user_id": 42}))
        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1
        assert result["user_id"] == 42

    def test_parses_string_input(self):
        result = parse_sns_message(json.dumps(_sns({"event_type": "range.status.updated", "range_id": 1})))
        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1

    def test_handles_non_wrapped_message(self):
        result = parse_sns_message({"event_type": "range.status.updated", "range_id": 1})
        assert result["event_type"] == "range.status.updated"


class TestProcessRangeEvent:
    def test_broadcasts_status_update_to_request_group(self):
        request_id = uuid4()
        group = range_event_group(str(request_id))
        layer, channel = _subscribe(group)

        process_range_event(
            _sns(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_id),
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )
        )

        msg = _receive(layer, channel)
        assert msg is not None
        assert msg["type"] == "range.status"
        assert msg["request_id"] == str(request_id)
        assert msg["new_status"] == ResourceStatus.PROVISIONING.value
        assert msg["error_message"] is None

    def test_includes_error_message_when_present(self):
        request_id = uuid4()
        layer, channel = _subscribe(range_event_group(str(request_id)))
        process_range_event(
            _sns(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_id),
                    "new_status": ResourceStatus.FAILED.value,
                    "error_message": "Subnet exhausted",
                }
            )
        )
        assert _receive(layer, channel)["error_message"] == "Subnet exhausted"

    def test_ignores_non_status_events(self):
        request_id = uuid4()
        layer, channel = _subscribe(range_event_group(str(request_id)))
        process_range_event(_sns({"event_type": "range.provisioned", "request_id": str(request_id)}))
        assert _receive(layer, channel) is None

    def test_does_not_broadcast_when_request_id_missing(self):
        # Subscribe broadly is not possible without a request_id group; assert the
        # handler returns without raising and emits nothing on a fresh channel.
        layer = get_channel_layer()
        channel = f"recv-{uuid4()}"
        async_to_sync(layer.group_add)("range_status_unknown", channel)
        process_range_event(_sns({"event_type": "range.status.updated", "new_status": "ready"}))
        assert _receive(layer, channel) is None


class TestProcessNgfwEvent:
    def test_broadcasts_to_app_group(self):
        app_id = str(uuid4())
        layer, channel = _subscribe(ngfw_event_group(app_id))
        process_ngfw_event(_sns({"event_type": EVENT_TYPE_NGFW, "app_id": app_id, "status": "ready"}))
        msg = _receive(layer, channel)
        assert msg is not None
        assert msg["type"] == "ngfw.status"
        assert msg["app_id"] == app_id
        assert msg["status"] == "ready"

    def test_ignores_invalid_app_id(self):
        layer, channel = _subscribe(ngfw_event_group("x"))
        process_ngfw_event(_sns({"event_type": EVENT_TYPE_NGFW, "app_id": None}))
        assert _receive(layer, channel) is None


class TestProcessEventRouting:
    def test_routes_range_event(self):
        request_id = uuid4()
        layer, channel = _subscribe(range_event_group(str(request_id)))
        process_event(
            _sns(
                {
                    "event_type": "range.status.updated",
                    "request_id": str(request_id),
                    "new_status": ResourceStatus.READY.value,
                }
            )
        )
        assert _receive(layer, channel) is not None

    def test_routes_ngfw_event(self):
        app_id = str(uuid4())
        layer, channel = _subscribe(ngfw_event_group(app_id))
        process_event(_sns({"event_type": EVENT_TYPE_NGFW, "app_id": app_id, "status": "ready"}))
        assert _receive(layer, channel) is not None

    def test_ignores_unknown_event_type(self):
        request_id = uuid4()
        layer, channel = _subscribe(range_event_group(str(request_id)))
        process_event(_sns({"event_type": "unknown.event", "request_id": str(request_id)}))
        assert _receive(layer, channel) is None
