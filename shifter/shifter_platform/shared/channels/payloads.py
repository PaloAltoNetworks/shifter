"""Static-typing contracts for Django Channels ``group_send`` payloads.

These ``TypedDict`` schemas describe the channel-layer events produced by
``mission_control.handlers`` and consumed by the websocket consumers in
``mission_control.status_consumers``.

This is a distinct contract family from the durable bus payloads in
``shared.messages.payloads``: the durable ``range.status.updated`` SQS event is
not the same thing as the ``range.status`` ``group_send`` payload consumed by
``RangeStatusConsumer.range_status``. Static typing only; the channel layer
still delivers plain dicts. See
``docs/architecture/typed-event-contracts-preflight-296.md``.
"""

from __future__ import annotations

from typing import Any, TypedDict


class RangeStatusChannelEvent(TypedDict):
    """``group_send`` payload dispatched to ``RangeStatusConsumer.range_status``.

    The ``type`` key (``"range.status"``) is how Channels routes the event to the
    consumer method.
    """

    type: str
    range_ref: dict[str, Any]
    request_id: str
    new_status: str
    error_message: str | None


class NGFWStatusChannelEvent(TypedDict):
    """``group_send`` payload dispatched to ``NGFWStatusConsumer.ngfw_status``.

    The ``type`` key (``"ngfw.status"``) is how Channels routes the event to the
    consumer method.
    """

    type: str
    app_id: str
    status: str | None
    state: dict[str, Any]
    serial_number: str | None
