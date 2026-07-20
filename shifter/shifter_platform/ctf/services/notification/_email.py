"""CTF notification email dispatch and rendering.

Houses the low-level email choke point (``_send_email``), template
rendering (``_render_email``), and the tokenless CTF login URL builder
(``_build_ctf_login_url``) shared by the participant- and organizer-facing
notification functions in ``ctf.services.notification``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ctf.models import CTFEvent

logger = logging.getLogger(__name__)


def _build_ctf_login_url() -> str:
    """Build the tokenless dedicated CTF participant login URL."""
    from django.conf import settings
    from django.urls import reverse

    path = reverse("ctf:ctf_login")
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    return f"{base}{path}"


def _send_email(
    recipient: str,
    subject: str,
    html_content: str,
    text_content: str,
) -> None:
    """Dispatch an email via the shared platform email service.

    Delegates to ``shared.email.send_email_async``, which submits the send
    to a background thread and returns immediately (fire-and-forget). This
    is the single CTF send choke point: callers never depend on a delivery
    result, so the triggering action is never blocked on SMTP latency
    (PLAT-103 clause 3). Delivery failures are logged inside the background
    worker but never raised or surfaced to the caller (clause 4). Uses
    ``CTF_FROM_EMAIL`` as the sender address.

    Args:
        recipient: Email address.
        subject: Email subject.
        html_content: HTML email body.
        text_content: Plain text email body.
    """
    from django.conf import settings

    from shared.email import send_email_async

    send_email_async(recipient, subject, html_content, text_content, from_email=settings.CTF_FROM_EMAIL)


def _render_email(
    template_name: str,
    context: dict[str, object],
    event: CTFEvent | None = None,
) -> tuple[str, str, str]:
    """Render email templates.

    If *event* is provided and has a custom template for the given
    notification type, the custom template is rendered from the database.
    Otherwise the default filesystem template is used.

    Args:
        template_name: Base name / notification type (e.g., "invitation").
        context: Template context.
        event: Optional event for custom template lookup.

    Returns:
        Tuple of (html_content, text_content, custom_subject).
        custom_subject is non-empty only when a custom template with a
        subject override is used; callers should prefer it over their
        default subject when non-empty.
    """
    # Map filesystem template names to NotificationType enum values where
    # they differ (the "invitation" template corresponds to the "invite" type).
    _TEMPLATE_TO_TYPE = {"invitation": "invite"}

    if event is not None:
        from ctf.models import CTFEmailTemplate

        lookup_type = _TEMPLATE_TO_TYPE.get(template_name, template_name)
        custom = CTFEmailTemplate.objects.filter(
            event=event,
            notification_type=lookup_type,
        ).first()
        if custom is not None:
            from ctf.services.email_template import (
                allowed_placeholders,
                build_safe_context,
                find_template_violations,
                render_safe_body,
            )

            # Organizer-authored bodies are untrusted: never hand them to the
            # Django template engine (CWE-1336). Validate against the flat
            # placeholder policy and fail closed to the trusted default
            # template on any unsupported syntax, even though writes are also
            # validated -- stored rows can predate validators or arrive via
            # admin / direct saves / restores.
            allowed = allowed_placeholders(lookup_type)
            violations = find_template_violations(custom.html_body, allowed) + find_template_violations(
                custom.text_body, allowed
            )
            if violations:
                logger.warning(
                    "Custom email template for event %s (%s) failed safe-render "
                    "validation; falling back to default template",
                    getattr(event, "pk", None),
                    lookup_type,
                )
            else:
                scalars = build_safe_context(context)
                html_content = render_safe_body(custom.html_body, scalars, escape=True)
                text_content = render_safe_body(custom.text_body, scalars, escape=False)
                return html_content, text_content, custom.subject or ""

    from shared.email import render_template

    html, text = render_template(f"ctf/email/{template_name}", context)
    return html, text, ""
