"""Administrator-triggered password reset dispatcher (PLAT-236, #1943).

An account-origin-aware credential-reset dispatcher whose first accepted
implementation is Django's proven local password-reset lifecycle. Only an
active, local (non-provider, non-CTF) account with a usable password and a valid
email is eligible for a Django reset:

- a provider-bound account must reset at its identity provider (setting a local
  Django password would be an authentication downgrade);
- a temporary CTF account stays owned by ``ctf.services.participant.credentials``.

Delivery reuses the configured email backend, the validated public ``SITE_URL``
origin, and the cross-worker credential-delivery budget. The administrator's
accepted request is strict-audited (secret-free) before delivery is scheduled on
transaction commit; no password, hash, token, URL, or email body is ever
returned in JSON, logged, or written to audit state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from management import admin_services, services
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.credential_delivery import credential_delivery_allowed
from shared.site_url import SiteUrlUnavailable, validated_site_url

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.contrib.auth.models import User
    from django.http import HttpRequest

    from management.services import AuditContext

logger = logging.getLogger(__name__)

_SUBJECT_TEMPLATE = "registration/password_reset_subject.txt"
_TEXT_TEMPLATE = "registration/password_reset_email.txt"
_HTML_TEMPLATE = "registration/password_reset_email.html"


class PasswordResetError(Exception):
    """A rejected password-reset request carrying a stable, safe error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _SingleUserPasswordResetForm(PasswordResetForm):
    """PasswordResetForm that only ever emails the one resolved, authorized user.

    Django's ``PasswordResetForm.get_users`` resolves recipients by
    case-insensitive email, and ``User.email`` is not unique, so the stock form
    could email a reset link to every account sharing the address, including
    accounts whose origin this command never checked (issue #1943 review F2). This
    subclass restricts delivery to the single target the Administer command
    already resolved and authorized, while keeping Django's token generation,
    validators, and delivery machinery unchanged.
    """

    def __init__(self, target_user: User, *args: Any, **kwargs: Any) -> None:
        self._target_user = target_user
        super().__init__(*args, **kwargs)

    def get_users(self, email: str) -> Iterator[User]:
        """Yield only the pre-resolved target when it can still receive a reset."""
        user = self._target_user
        if user.has_usable_password() and user.is_active:
            yield user


def _has_valid_email(user: User) -> bool:
    """Return whether the user has a present, syntactically valid email."""
    if not user.email:
        return False
    try:
        validate_email(user.email)
    except ValidationError:
        return False
    return True


def reset_eligibility(user: User) -> tuple[bool, str]:
    """Return ``(eligible, reason)`` for an administrator-triggered Django reset.

    Eligible only for an active, local, non-CTF account with a usable password
    and a valid email that is not soft-deleted. ``reason`` is a stable, safe code
    for an ineligible account and empty when eligible.
    """
    profile = services.safe_user_profile(user)
    origin = admin_services.classify_account_origin(profile)
    failures = [
        (profile is not None and profile.deleted_at is not None, "account_deleted"),
        (not user.is_active, "account_inactive"),
        (origin == "ctf", "ctf_account_uses_event_credentials"),
        (origin == "provider", "provider_account_resets_at_provider"),
        (not user.has_usable_password(), "no_usable_password"),
        (not _has_valid_email(user), "no_valid_email"),
    ]
    for failed, reason in failures:
        if failed:
            return False, reason
    return True, ""


def request_password_reset(user: User, *, audit: AuditContext, request: HttpRequest | None = None) -> None:
    """Send an administrator-triggered Django password-reset email to ``user``.

    Validates eligibility, consumes the delivery budget, records a strict
    secret-free audit event, and schedules Django's ``PasswordResetForm`` email
    on transaction commit using the validated public origin.

    Raises:
        PasswordResetError: If the account is ineligible, the budget is
            exhausted, or the public origin is unavailable.
    """
    eligible, reason = reset_eligibility(user)
    if not eligible:
        raise PasswordResetError("reset_ineligible", f"This account is not eligible for a password reset ({reason}).")

    try:
        site_url = validated_site_url()
    except SiteUrlUnavailable as exc:
        raise PasswordResetError("reset_delivery_unavailable", "Password reset delivery is unavailable.") from exc

    if not credential_delivery_allowed(user.id):
        raise PasswordResetError("reset_throttled", "Too many reset requests for this account; try again later.")

    parsed = urlsplit(site_url)
    domain = parsed.netloc
    use_https = parsed.scheme == "https"

    form = _SingleUserPasswordResetForm(user, {"email": user.email})
    if not form.is_valid():
        # The email was already validated by reset_eligibility; a failure here is
        # an unexpected internal condition, not attacker-controlled.
        raise PasswordResetError("reset_ineligible", "This account is not eligible for a password reset.")

    def _deliver() -> None:
        """Send the Django reset email after the surrounding transaction commits."""
        form.save(
            domain_override=domain,
            use_https=use_https,
            from_email=settings.DEFAULT_FROM_EMAIL,
            subject_template_name=_SUBJECT_TEMPLATE,
            email_template_name=_TEXT_TEMPLATE,
            html_email_template_name=_HTML_TEMPLATE,
            token_generator=default_token_generator,
            request=request,
        )

    with transaction.atomic():
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.USER,
                entity_id=user.id,
                action=AuditAction.UPDATE,
                actor_type=audit.actor_type,
                actor_id=audit.actor_id,
                new_state={"outcome": "password_reset_email_scheduled"},
                context="administrator password reset requested",
                request_id=audit.request_id,
                source_ip=audit.source_ip,
                user_agent=audit.user_agent,
            ),
            strict=True,
        )
        transaction.on_commit(_deliver)

    logger.info("Password reset email scheduled for user_id=%s", user.id)
