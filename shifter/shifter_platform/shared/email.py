"""Shared email templating and delivery service (PLAT-103).

Provides platform-wide helpers for rendering Django email templates and
sending multipart (HTML + plain-text) messages.  Other apps should import
from this module rather than assembling ``EmailMultiAlternatives`` directly.

Key features
~~~~~~~~~~~~
* ``render_template`` — renders an HTML/text template pair with context
  variable substitution.
* ``send_email`` — synchronous send with exception handling (failures are
  logged, never raised).
* ``send_email_async`` — fire-and-forget dispatch to a background thread so
  the triggering action is never blocked by SMTP latency.
"""

from __future__ import annotations

import atexit
import logging
from concurrent.futures import ThreadPoolExecutor

from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)

# Lazy-initialised thread pool for async delivery.  The small pool size
# prevents runaway threads while still allowing several concurrent sends.
_executor: ThreadPoolExecutor | None = None
_MAX_WORKERS = 4


def _get_executor() -> ThreadPoolExecutor:
    """Return (and lazily create) the module-level thread pool."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="email")
        atexit.register(_executor.shutdown, wait=False)
    return _executor


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_template(template_path: str, context: dict) -> tuple[str, str]:
    """Render an HTML + plain-text email template pair.

    Args:
        template_path: Path prefix relative to the templates root **without**
            the extension.  For example ``"ctf/email/invitation"`` will render
            ``ctf/email/invitation.html`` and ``ctf/email/invitation.txt``.
        context: Template context dict for variable substitution.

    Returns:
        ``(html_content, text_content)`` tuple.
    """
    from django.template.loader import render_to_string

    html_content = render_to_string(f"{template_path}.html", context)
    text_content = render_to_string(f"{template_path}.txt", context)
    return html_content, text_content


def send_email(
    recipient: str,
    subject: str,
    html_content: str,
    text_content: str,
    *,
    from_email: str | None = None,
) -> bool:
    """Send a multipart email synchronously.

    Failures are logged at ERROR level but never raised — the caller is
    guaranteed not to crash due to email delivery issues.

    Args:
        recipient: Destination email address.
        subject: Email subject line.
        html_content: HTML body.
        text_content: Plain-text body.
        from_email: Sender address.  Falls back to ``DEFAULT_FROM_EMAIL``.

    Returns:
        ``True`` if the message was accepted for delivery, ``False`` otherwise.
    """
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    sender = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=sender,
            to=[recipient],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        return True
    except Exception:
        logger.exception("Failed to send email to %s", safe_log_value(recipient))
        return False


def send_email_async(
    recipient: str,
    subject: str,
    html_content: str,
    text_content: str,
    *,
    from_email: str | None = None,
) -> None:
    """Dispatch email delivery to a background thread.

    This is fire-and-forget — the calling thread returns immediately.
    Delivery failures are logged but never propagated to the caller.

    Args:
        recipient: Destination email address.
        subject: Email subject line.
        html_content: HTML body.
        text_content: Plain-text body.
        from_email: Sender address.  Falls back to ``DEFAULT_FROM_EMAIL``.
    """
    _get_executor().submit(send_email, recipient, subject, html_content, text_content, from_email=from_email)
