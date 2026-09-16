"""Outbound webhooks for event milestones (CTF-1203).

Deliveries run on a small background thread pool (same pattern as
:mod:`shared.email`): the triggering action never blocks on, or fails
because of, a receiver. Each delivery retries with exponential backoff
inside its worker before recording a final status on the webhook row.
Payloads carry the webhook event type, an ISO timestamp, and entity data;
a per-webhook secret yields an ``X-Shifter-Signature`` HMAC-SHA256 header.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from ctf.models import CTFEvent, CTFWebhook

logger = logging.getLogger(__name__)

WEBHOOK_EVENT_TYPES = frozenset({"flag_solve", "first_blood", "event_state_change", "participant_registered"})


def create_event_webhook(
    event: CTFEvent,
    *,
    url: str,
    secret: str,
    subscribed_events: list[str],
    actor_id: int,
) -> CTFWebhook:
    """Register a webhook on an event, asserting the ``config`` capability (#1922).

    The mutation lives behind this service boundary rather than in the view so
    the event policy is enforced at the final write, not only at the HTTP
    resolver.
    """
    from ctf.enums import EventCapability
    from ctf.models import CTFWebhook
    from ctf.services.authorization import assert_event_capability

    assert_event_capability(actor_id, event, EventCapability.CONFIG)
    return CTFWebhook.objects.create(event=event, url=url, secret=secret, subscribed_events=subscribed_events)


def delete_event_webhook(webhook_id: UUID, *, actor_id: int) -> None:
    """Soft-delete a webhook, asserting the ``config`` capability on its event (#1922).

    Raises:
        CTFNotFoundError: If the webhook does not exist.
        CTFPermissionError: If ``actor_id`` lacks the ``config`` capability.
    """
    from ctf.enums import EventCapability
    from ctf.exceptions import CTFNotFoundError
    from ctf.models import CTFWebhook
    from ctf.services.authorization import assert_event_capability

    webhook = CTFWebhook.objects.select_related("event").filter(pk=webhook_id, deleted_at__isnull=True).first()
    if webhook is None:
        raise CTFNotFoundError("Webhook not found", details={"webhook_id": str(webhook_id)})
    assert_event_capability(actor_id, webhook.event, EventCapability.CONFIG)
    webhook.delete(soft=True)


_DELIVERY_TIMEOUT_SECONDS = 10
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 5

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ctf-webhook")


def emit_webhook(event: CTFEvent, event_type: str, data: dict[str, Any]) -> int:
    """Queue delivery of one milestone to every subscribed webhook.

    Returns the number of deliveries queued. Never raises: webhook problems
    must not affect the triggering action.
    """
    from django.utils import timezone

    from ctf.models import CTFWebhook

    try:
        webhooks = [
            hook
            for hook in CTFWebhook.objects.filter(event=event, active=True, deleted_at__isnull=True)
            if not hook.subscribed_events or event_type in hook.subscribed_events
        ]
        if not webhooks:
            return 0
        body = json.dumps(
            {
                "event_type": event_type,
                "timestamp": timezone.now().isoformat(),
                "ctf_event": {"id": str(event.pk), "name": event.name},
                "data": data,
            },
            default=str,
        ).encode()
        for hook in webhooks:
            _executor.submit(_deliver_with_retries, hook.pk, hook.url, hook.secret, body)
        return len(webhooks)
    except Exception:
        logger.exception("Failed to queue %s webhooks for event %s", event_type, event.pk)
        return 0


def _deliver_with_retries(webhook_pk: UUID, url: str, secret: str, body: bytes) -> None:
    """POST with exponential backoff (5s, 25s) and record the final status."""
    import requests

    headers = {"Content-Type": "application/json"}
    if secret:
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Shifter-Signature"] = f"sha256={signature}"

    status = "failed"
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.post(url, data=body, headers=headers, timeout=_DELIVERY_TIMEOUT_SECONDS)
            if response.ok:
                status = f"ok:{response.status_code}"
                break
            status = f"failed:{response.status_code}"
        except requests.RequestException as exc:
            status = f"failed:{type(exc).__name__}"
        if attempt < _MAX_ATTEMPTS:
            time.sleep(_BACKOFF_BASE_SECONDS**attempt)
    _record_delivery(webhook_pk, status)


def _record_delivery(webhook_pk: UUID, status: str) -> None:
    """Persist the delivery outcome; best-effort (worker thread)."""
    from django.utils import timezone

    from ctf.models import CTFWebhook

    try:
        CTFWebhook.objects.filter(pk=webhook_pk).update(last_status=status, last_delivery_at=timezone.now())
        if status.startswith("failed"):
            logger.warning("Webhook %s delivery failed: %s", webhook_pk, status)
    except Exception:
        logger.exception("Failed to record webhook delivery for %s", webhook_pk)
