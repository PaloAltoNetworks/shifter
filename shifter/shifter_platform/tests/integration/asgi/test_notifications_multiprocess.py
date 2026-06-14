"""Cross-process notification fan-out test through real Redis (#924, TEST-6).

A ``WebsocketCommunicator`` alone is same-process evidence. To prove the
property the issue actually cares about — a notification published on one
worker reaching a browser connected to another — this test spawns a genuinely
separate OS process that publishes through the Redis channel layer, while the
parent process holds the websocket on the real ``config.asgi.application``.
Only the Redis posture is expected to deliver across processes, so the test is
Redis-marked and skips when Redis is unreachable.

The child does only ``group_send`` (no DB): the notification row is created in
the parent's test DB and the parent's consumer reads it back, so the test does
not depend on the SQLite test database being shareable across processes.
"""

from __future__ import annotations

import multiprocessing
import os
import sys

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from shared.channels.groups import notification_user_topic_group

from . import _redis_fanout_child
from .conftest import NOTIFICATION_TOPIC, _redis_endpoint, make_notification

NOTIFICATIONS_PATH = "/ws/notifications/"


def _publish_from_child(group: str, notification_id: int) -> int:
    """Spawn a separate process to publish the dispatch; return its exit code."""
    host, port = _redis_endpoint()
    env = {
        "TESTING": os.environ.get("TESTING", "1"),
        "DJANGO_SECRET_KEY": os.environ.get("DJANGO_SECRET_KEY", "ws-multiprocess-secret"),
        "CHANNEL_LAYER_BACKEND": "redis",
        "REDIS_HOST": host,
        "REDIS_PORT": str(port),
    }
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_redis_fanout_child.publish_dispatch,
        args=(list(sys.path), env, group, notification_id),
    )
    proc.start()
    proc.join(timeout=60)
    if proc.is_alive():  # pragma: no cover - safety net for a hung child
        proc.terminate()
        proc.join(timeout=5)
    return proc.exitcode


@pytest.mark.redis
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cross_process_fanout_via_redis(
    asgi_application, ws_user, ws_headers, registered_notification_type, redis_channel_layer
):
    """A notification published by a separate process reaches the websocket."""
    communicator = WebsocketCommunicator(asgi_application, NOTIFICATIONS_PATH, headers=ws_headers)
    connected, _ = await communicator.connect()
    assert connected is True
    await communicator.send_json_to({"type": "subscribe", "topic": NOTIFICATION_TOPIC})
    assert (await communicator.receive_json_from())["type"] == "subscribed"

    # Row lives in the parent's DB; the child only publishes over Redis.
    notification = await sync_to_async(make_notification)(ws_user, payload={"msg": "cross-process"})
    group = notification_user_topic_group(ws_user.id, NOTIFICATION_TOPIC)

    exitcode = await sync_to_async(_publish_from_child)(group, notification.id)
    assert exitcode == 0

    message = await communicator.receive_json_from(timeout=10)
    assert message["type"] == "notification"
    assert message["id"] == notification.id
    assert message["payload"] == {"msg": "cross-process"}
    await communicator.disconnect()
