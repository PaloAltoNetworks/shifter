"""Platform password-reset landing views (PLAT-236, #1943).

Thin subclasses of Django's proven password-reset confirm/complete views. The
administrator-triggered reset email (``management.password_reset``) links to
``password_reset_confirm``; Django validates the signed UID/token, enforces the
configured password validators, saves the new password, invalidates the reset
token, and redirects to ``password_reset_complete`` so the raw token leaves the
browser URL. The confirm view additionally records a strict, secret-free audit
event for the completed password change.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.views import PasswordResetCompleteView, PasswordResetConfirmView
from django.db import transaction
from django.urls import reverse_lazy

from management.services import reset_eligibility
from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
    AuditEvent,
    audit_log,
    get_client_ip,
    get_request_id,
)

if TYPE_CHECKING:
    from django.http import HttpResponse

logger = logging.getLogger(__name__)


class PlatformPasswordResetConfirmView(PasswordResetConfirmView):
    """Django reset-confirm view that re-checks eligibility and audits the change."""

    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")

    def form_valid(self, form: SetPasswordForm[Any]) -> HttpResponse:
        # PasswordResetConfirmView.dispatch validates the token and sets self.user
        # before form_valid runs; assert it for the type checker.
        assert self.user is not None
        # Django's token validity does not include is_active, deleted_at, or the
        # account-origin binding, so a reset URL issued while an account was
        # eligible could otherwise be redeemed after it was suspended, deleted,
        # or provider-bound (issue #1943 review cycle-2 F3). Re-fetch and lock the
        # target and re-run the same eligibility gate before saving; reject the
        # redemption as an invalid link if any condition no longer holds. Save the
        # new password and its strict audit in one transaction so a completed
        # credential change is never left without its audit row (review F4).
        with transaction.atomic():
            # Lock the user row only. Adding select_related("profile") here would
            # join the nullable reverse one-to-one and raise "FOR UPDATE cannot be
            # applied to the nullable side of an outer join" on PostgreSQL (#1943);
            # reset_eligibility loads the profile in a separate query.
            locked = get_user_model().objects.select_for_update().get(pk=self.user.pk)
            eligible, reason = reset_eligibility(locked)
            if not eligible:
                logger.warning("Password reset redemption rejected: ineligible (%s) user_id=%s", reason, locked.id)
                context = self.get_context_data(form=form)
                context["validlink"] = False
                return self.render_to_response(context)

            response = super().form_valid(form)
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.USER,
                    entity_id=self.user.id,
                    action=AuditAction.UPDATE,
                    actor_type=AuditActorType.USER,
                    actor_id=self.user.id,
                    new_state={"outcome": "password_changed_via_reset"},
                    context="password changed via reset link",
                    request_id=get_request_id(self.request),
                    source_ip=get_client_ip(self.request),
                    user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:255],
                ),
                strict=True,
            )
        return response


class PlatformPasswordResetCompleteView(PasswordResetCompleteView):
    """Django reset-complete confirmation page."""

    template_name = "registration/password_reset_complete.html"
