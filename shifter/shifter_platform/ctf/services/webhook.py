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
import http.client
import json
import logging
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
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
    from ctf.exceptions import CTFValidationError
    from ctf.models import CTFWebhook
    from ctf.services.authorization import assert_event_capability
    from ctf.validators._ssrf import is_blocked_url

    assert_event_capability(actor_id, event, EventCapability.CONFIG)
    if not isinstance(url, str) or not url.startswith("https://") or is_blocked_url(url):
        raise CTFValidationError("Webhook destination is unavailable.", code="CTF_WEBHOOK_DESTINATION_BLOCKED")
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


def _post_pinned(url: str, body: bytes, headers: dict[str, str]) -> int:
    """POST over TLS to one validated IP; redirects never become new requests."""
    from ctf.validators import _ssrf
    from ctf.validators._http import _request_target

    parsed_tuple = _ssrf._safe_parse_url(url)
    if parsed_tuple is None:
        raise _ssrf._BlockedDestinationError("Invalid webhook destination")
    parsed, hostname, port = parsed_tuple
    if parsed.scheme != "https" or parsed.username or parsed.password or hostname in _ssrf._BLOCKED_HOSTNAMES:
        raise _ssrf._BlockedDestinationError("Invalid webhook destination")
    pinned_ips = _ssrf._resolve_and_validate(hostname, port)
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    for pinned_ip in pinned_ips:
        connection = _ssrf._build_https_connection(
            hostname=hostname,
            pinned_ip=pinned_ip,
            port=port,
            timeout=_DELIVERY_TIMEOUT_SECONDS,
            context=context,
        )
        try:
            connection.request("POST", _request_target(parsed), body=body, headers=headers)
            return int(connection.getresponse().status)
        except (OSError, http.client.HTTPException):
            continue
        finally:
            with suppress(Exception):
                connection.close()
    raise OSError("Webhook transport unavailable")


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
            _executor.submit(_deliver_with_retries, hook.pk, hook.url, hook.secret, body, event_type)
        return len(webhooks)
    except Exception:
        logger.exception("Failed to queue %s webhooks for event %s", event_type, event.pk)
        return 0


def _delivery_is_current(webhook_pk: UUID, url: str, secret: str, event_type: str | None) -> bool:
    """Deny a queued send after the subscription or event binding changes."""
    from ctf.models import CTFWebhook

    row = CTFWebhook.objects.filter(
        pk=webhook_pk, active=True, deleted_at__isnull=True, event__deleted_at__isnull=True
    ).first()
    return bool(
        row is not None
        and row.url == url
        and hmac.compare_digest(row.secret, secret)
        and (event_type is None or not row.subscribed_events or event_type in row.subscribed_events)
    )


def _deliver_with_retries(webhook_pk: UUID, url: str, secret: str, body: bytes, event_type: str | None = None) -> None:
    """Recheck the live subscription before each pinned POST and record the outcome."""
    from django.db import DatabaseError

    from ctf.validators._ssrf import _BlockedDestinationError

    headers = {"Content-Type": "application/json"}
    if secret:
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Shifter-Signature"] = f"sha256={signature}"

    status = "failed"
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            if not _delivery_is_current(webhook_pk, url, secret, event_type):
                status = "failed:revoked"
                break
            response_status = _post_pinned(url, body, headers)
            if 200 <= response_status < 300:
                status = f"ok:{response_status}"
                break
            status = f"failed:{response_status}"
        except _BlockedDestinationError:
            status = "failed:blocked_destination"
            break
        except DatabaseError:
            status = "failed:unavailable"
            break
        except (OSError, http.client.HTTPException):
            status = "failed:transport"
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
