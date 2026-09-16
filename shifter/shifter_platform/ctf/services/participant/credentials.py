"""Participant credential rotation and secret-free credential delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_variables

from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFParticipant

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from shared.audit import RequestAudit

_PASSWORD_KINDS = frozenset({"generated", "set"})


@dataclass(frozen=True, slots=True, repr=False)
class ParticipantPasswordIssuance:
    """Volatile result returned only by a successful password reset/set."""

    participant_id: UUID
    event_id: UUID
    username: str
    password: str
    kind: str


def _locked_password_target(participant_id: UUID) -> tuple[CTFParticipant, User]:
    """Load a live isolated password target under a row lock."""
    try:
        participant = (
            CTFParticipant.objects.select_for_update(of=("self",))
            .select_related("event", "user", "user__profile")
            .get(pk=participant_id, deleted_at__isnull=True)
        )
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError("Participant not found", details={"participant_id": str(participant_id)}) from None
    if participant.user is None or not participant.user.is_active or not participant.user.profile.is_ctf_account:
        raise CTFValidationError("Participant has no active account", code="CTF_ACCOUNT_REQUIRED")
    return participant, participant.user


def _audit_participant_password_issuance(
    participant: CTFParticipant,
    *,
    actor: User,
    kind: str,
    request_audit: RequestAudit | None,
) -> None:
    """Strict-audit the mutation with identifiers only."""
    from shared.audit import (
        AuditAction,
        AuditActorType,
        AuditEntityType,
        AuditEvent,
        RequestAudit,
        audit_log,
    )

    attribution = request_audit or RequestAudit()
    user_id = participant.user_id
    if user_id is None:
        raise CTFValidationError("Participant has no active account", code="CTF_ACCOUNT_REQUIRED")
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.USER,
            entity_id=user_id,
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor.pk,
            new_state={
                "participant_id": str(participant.pk),
                "event_id": str(participant.event_id),
                "issuance_kind": kind,
            },
            context=f"ctf_participant_password_{kind}",
            source_ip=attribution.source_ip,
            user_agent=attribution.user_agent,
            request_id=attribution.request_id,
        ),
        strict=True,
    )


@sensitive_variables("password", "issued_password")
def reset_participant_password(
    participant_id: UUID,
    *,
    actor: User,
    kind: str,
    password: str | None = None,
    request_audit: RequestAudit | None = None,
) -> ParticipantPasswordIssuance:
    """Issue one generated or organizer-supplied participant password."""
    if kind not in _PASSWORD_KINDS or (kind == "generated" and password is not None):
        raise CTFValidationError("Invalid participant password request", code="CTF_INVALID_PASSWORD_REQUEST")
    with transaction.atomic():
        participant, user = _locked_password_target(participant_id)
        from ctf.services.event import actor_has_event_capability
        from ctf.services.participant.accounts import generate_participant_password

        if not actor_has_event_capability(actor, participant.event, "participants"):
            raise CTFValidationError(
                "Only an event participant manager may reset this account",
                code="CTF_PERMISSION_DENIED",
            )
        if kind == "set":
            if password is None:
                raise CTFValidationError("A new password is required", code="CTF_INVALID_PASSWORD_REQUEST")
            from ctf.services.participant.accounts import _validate_participant_password

            _validate_participant_password(password, user=user)
            issued_password = password
        else:
            issued_password = generate_participant_password(user=user)
        user.set_password(issued_password)
        user.save(update_fields=["password"])
        from management.services import set_ctf_password_change_required
        from shared.api_tokens.models import ApiToken

        set_ctf_password_change_required(user, True)
        ApiToken.objects.filter(created_by=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
        _audit_participant_password_issuance(
            participant,
            actor=actor,
            kind=kind,
            request_audit=request_audit,
        )

    return ParticipantPasswordIssuance(
        participant_id=participant.pk,
        event_id=participant.event_id,
        username=user.username,
        password=issued_password,
        kind=kind,
    )


def reset_participant_credentials(participant_id: UUID) -> CTFParticipant:
    """Deprecated compatibility path: resend login information without a secret."""
    with transaction.atomic():
        participant, user = _locked_password_target(participant_id)
    if participant.email:
        from django.utils.html import escape

        from ctf.services.notification import _build_ctf_login_url, _send_email

        login_url = _build_ctf_login_url()
        username = user.username
        _send_email(
            recipient=participant.email,
            subject=f"CTF login for {participant.event.name}",
            html_content=f"<p>Username: {escape(username)}</p><p>Login: {escape(login_url)}</p>",
            text_content=f"Username: {username}\nLogin: {login_url}",
        )
    return participant


@sensitive_variables("candidate")
def participant_password_is_reused(user: User, candidate: str) -> bool:
    """Check current and explicit event-shared credentials inside the service."""
    if user.check_password(candidate):
        return True
    from ctf.services.participant.accounts import live_participant_for_user

    participant = live_participant_for_user(user)
    if participant is None:
        return False
    event_shared = participant.event.participant_password_override or ""
    return bool(event_shared.strip()) and constant_time_compare(candidate, event_shared)
