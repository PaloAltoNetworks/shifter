"""Static-typing contracts for durable bus (SNS/SQS/Pub-Sub) event payloads.

These ``TypedDict`` schemas describe the *wire shape* of events produced by the
Shifter Engine provisioner (``shifter/engine/provisioner/events.py``) and
consumed by the platform SQS handlers (``engine.handlers``, ``cms.handlers``,
``mission_control.handlers``).

They are **static typing only**. Messages still arrive from SQS/Pub-Sub as
untrusted dictionaries, so the handler-side runtime trust boundary — envelope
unwrapping (``parse_sns_message``), ``ResourceStatus`` validation, and ownership
checks — is unchanged. A ``TypedDict`` annotation is not a permission check or a
data validator. See ``docs/architecture/typed-event-contracts-preflight-296.md``.

Names carry a ``Payload`` suffix to stay distinct from the Pydantic *producer*
models in ``cyberscript.messages.events`` (``RangeStatusUpdatedEvent`` etc.).
Channel-layer ``group_send`` payloads are a separate contract family in
``shared.channels.payloads``.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class EventEnvelope(TypedDict):
    """Common metadata on every durable range/NGFW event.

    Built by the provisioner's ``_create_event`` / ``publish_ngfw_event``.
    """

    event_type: str
    event_id: str
    timestamp: str
    request_id: str


class RangeStatusUpdatedPayload(EventEnvelope):
    """``range.status.updated`` — the only range event that mutates model state."""

    range_id: int
    user_id: int
    new_status: str
    error_message: str | None


class RangeProvisionedPayload(EventEnvelope):
    """``range.provisioned`` — notification only (no instance/subnet/pulumi state)."""

    range_id: int
    user_id: int


class NGFWEventPayload(EventEnvelope):
    """``ngfw.event`` — NGFW lifecycle notification.

    Carries ``instance_id``/``app_id`` rather than ``range_id``/``user_id``.
    ``serial_number`` is present only on "ready" events; ``state`` is part of the
    declared contract (``cyberscript.messages.events.NGFWEvent``) and is not
    populated by the current provisioner producer.
    """

    instance_id: str
    app_id: str | None
    status: str
    serial_number: NotRequired[str]
    state: NotRequired[dict[str, Any] | None]
