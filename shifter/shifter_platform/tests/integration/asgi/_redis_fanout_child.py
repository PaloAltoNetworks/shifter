"""Child-process entrypoint for the cross-process Redis fan-out test (#924).

Lives in its own light module (only stdlib at import time; Django/Channels are
imported lazily inside the function) so a ``multiprocessing`` spawn child can
import it without pulling in pytest or the heavy test module. The child is a
genuinely separate OS process that publishes to the Redis channel layer; the
parent test process receives the message over its real ASGI websocket, proving
fan-out crosses the process boundary through Redis.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence


def publish_dispatch(sys_path: Sequence[str], env: Mapping[str, str], group: str, notification_id: int) -> None:
    """Set up Django in a fresh process and group_send one notification dispatch."""
    for path in sys_path:
        if path not in sys.path:
            sys.path.insert(0, path)
    os.environ.update(env)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    async_to_sync(layer.group_send)(group, {"type": "notification.dispatch", "notification_id": notification_id})
