"""Lifecycle for isolated, temporary CTF participant accounts."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFNotFoundError, CTFValidationError
from ctf.models import CTFEvent, CTFParticipant
from ctf.services.range import request_event_provisioning
from management.services import configure_temporary_ctf_account
from shared.auth import CTF_PARTICIPANT_GROUP

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User
else:
    User = get_user_model()

_HANDLE_RE = re.compile(r"^range-[a-z0-9][a-z0-9-]{2,42}$")
_MAX_GENERATED_ACCOUNTS = 100
_HANDLE_ATTEMPTS = 8


@sensitive_variables()
def _validate_bootstrap_credential(candidate: str) -> None:
    """Fail closed when a configured bootstrap source violates password policy.

    The organizer form already validates ``participant_password_override``, but
    settings, scripts, direct model writes, and pre-existing rows all bypass that
    form, so the service resolver re-applies the canonical validators. A
    non-conforming source raises a controlled CTF error instead of surfacing a
    Django ``ValidationError`` as a 500.
    """
    from django.contrib.auth.password_validation import validate_password

    try:
        validate_password(candidate)
    except ValidationError as exc:
        raise CTFValidationError(
            "Configured CTF participant bootstrap credential does not meet the password policy.",
            code="CTF_BOOTSTRAP_CREDENTIAL_INVALID",
        ) from exc


@sensitive_variables()
def effective_bootstrap_password(event: CTFEvent) -> str:
    """Resolve the event or platform bootstrap credential, failing closed.

    Accepted sources, in order: the event's encrypted
    ``participant_password_override`` and an explicitly configured
    ``CTF_DEFAULT_PARTICIPANT_PASSWORD``. Each non-blank source is validated
    against the canonical password policy before use. No repository literal,
    settings constant, or implicit default may ever authenticate an account:
    when neither source is configured this raises ``CTFValidationError`` so
    account creation, attachment, reset, reveal, and the bootstrap-reuse check
    all refuse rather than fall back to a shared, guessable credential.
    """
    override = getattr(event, "participant_password_override", "") or ""
    # Presence is decided on the stripped value so a whitespace-only source is
    # treated as unconfigured (blank means unavailable, not a valid password);
    # the original candidate is preserved for validation and use.
    if override.strip():
        _validate_bootstrap_credential(override)
        return override
    platform_default = getattr(settings, "CTF_DEFAULT_PARTICIPANT_PASSWORD", "") or ""
    if platform_default.strip():
        _validate_bootstrap_credential(platform_default)
        return platform_default
    raise CTFValidationError(
        "No secure CTF participant bootstrap credential is configured for this event.",
        code="CTF_BOOTSTRAP_CREDENTIAL_UNAVAILABLE",
    )


def generate_participant_username() -> str:
    """Generate an email-disjoint CTF username."""
    return f"range-{secrets.token_hex(4)}"


def normalize_participant_username(username: str) -> str:
    """Normalize and validate an organizer-supplied CTF username."""
    normalized = username.strip().lower()
    if not _HANDLE_RE.fullmatch(normalized):
        raise CTFValidationError(
            "Username must start with 'range-' and contain only lowercase letters, numbers, and hyphens.",
            code="CTF_INVALID_USERNAME",
        )
    field = User._meta.get_field("username")
    try:
        field.run_validators(normalized)
    except ValidationError as exc:
        raise CTFValidationError("Invalid participant username", code="CTF_INVALID_USERNAME") from exc
    return normalized


def _new_user(password: str, username_factory: Callable[[], str]) -> User:
    """Create a unique isolated user within a bounded retry loop."""
    for _ in range(_HANDLE_ATTEMPTS):
        username = normalize_participant_username(username_factory())
        try:
            with transaction.atomic():
                return User.objects.create_user(username=username, email="", password=password)
        except IntegrityError:
            continue
    raise CTFValidationError("Unable to allocate a unique participant username", code="CTF_USERNAME_EXHAUSTED")


def _validate_account_request(count: int, email: str) -> None:
    """Validate organizer-supplied batch inputs."""
    if count < 1 or count > _MAX_GENERATED_ACCOUNTS:
        raise CTFValidationError(
            f"Account count must be between 1 and {_MAX_GENERATED_ACCOUNTS}",
            code="CTF_INVALID_ACCOUNT_COUNT",
        )
    if count > 1 and email:
        raise CTFValidationError("Batch-created accounts cannot share a delivery email", code="CTF_BATCH_EMAIL")


def _event_for_account_creation(event_id: UUID, count: int) -> tuple[CTFEvent, int]:
    """Lock and validate the event, returning its current seat count."""
    try:
        event = CTFEvent.objects.select_for_update().get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError("Event not found", details={"event_id": str(event_id)}) from None
    if event.registration_deadline and timezone.now() > event.registration_deadline:
        raise CTFValidationError(
            "Registration deadline has passed",
            code="CTF_REGISTRATION_DEADLINE_PASSED",
        )
    active_count = event.participants.filter(deleted_at__isnull=True).count()
    if event.max_participants and active_count + count > event.max_participants:
        raise CTFValidationError("Event has reached maximum participants", code="CTF_MAX_PARTICIPANTS_REACHED")
    return event, active_count


@sensitive_variables("password")
def create_participant_accounts(
    event_id: UUID,
    *,
    count: int,
    email: str = "",
    display_name: str = "",
) -> list[CTFParticipant]:
    """Create isolated participant seats and enqueue canonical provisioning."""
    _validate_account_request(count, email)

    created: list[CTFParticipant] = []
    with transaction.atomic():
        event, active_count = _event_for_account_creation(event_id, count)
        group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
        password = effective_bootstrap_password(event)
        now = timezone.now()
        for index in range(count):
            user = _new_user(password, generate_participant_username)
            user.groups.set([group])
            configure_temporary_ctf_account(user, event.pk)
            participant = CTFParticipant.objects.create(
                event=event,
                user=user,
                email=email.strip().lower() if count == 1 else "",
                name=display_name.strip() or f"Participant {active_count + index + 1}",
                status=ParticipantStatus.REGISTERED.value,
                registered_at=now,
            )
            created.append(participant)
        transaction.on_commit(lambda: request_event_provisioning(event.pk, source="participant_accounts"))
    return created


@sensitive_variables("password")
def attach_isolated_account(participant: CTFParticipant) -> CTFParticipant:
    """Attach a fresh marked account to an existing unlinked participant."""
    if participant.user_id is not None:
        raise CTFValidationError("Participant already has an account", code="CTF_ACCOUNT_EXISTS")
    password = effective_bootstrap_password(participant.event)
    user = _new_user(password, generate_participant_username)
    group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.set([group])
    configure_temporary_ctf_account(user, participant.event_id)
    participant.user = user
    participant.status = ParticipantStatus.REGISTERED.value
    participant.registered_at = timezone.now()
    participant.save(update_fields=["user", "status", "registered_at", "updated_at"])
    transaction.on_commit(lambda: request_event_provisioning(participant.event_id, source="participant_accounts"))
    return participant


def _locked_rename_target(participant_id: UUID) -> CTFParticipant:
    """Load the rename target under a row lock, or raise not-found."""
    try:
        return (
            CTFParticipant.objects.select_for_update(of=("self",))
            .select_related("event", "user", "user__profile")
            .get(pk=participant_id, deleted_at__isnull=True)
        )
    except CTFParticipant.DoesNotExist:
        raise CTFNotFoundError("Participant not found", details={"participant_id": str(participant_id)}) from None


def _apply_username_rename(participant: CTFParticipant, normalized: str, actor: User | AnonymousUser) -> None:
    """Write and audit a username change on an isolated CTF account."""
    if participant.user is None or not participant.user.profile.is_ctf_account:
        raise CTFValidationError("Participant has no isolated CTF account", code="CTF_ACCOUNT_REQUIRED")
    old_username = participant.user.username
    participant.user.username = normalized
    try:
        participant.user.save(update_fields=["username"])
    except IntegrityError as exc:
        raise CTFValidationError("Username is already in use", code="CTF_DUPLICATE_USERNAME") from exc
    from shared.audit import (
        AuditAction,
        AuditActorType,
        AuditEntityType,
        AuditEvent,
        audit_log,
    )

    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.USER,
            entity_id=participant.user.pk,
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor.pk,
            previous_state={"username": old_username},
            new_state={"username": normalized},
            context="CTF participant username rename",
        ),
        strict=True,
    )


def rename_participant_username(
    participant_id: UUID,
    username: str,
    *,
    actor: User | AnonymousUser,
) -> CTFParticipant:
    """Rename a marked participant account (organizer or delegated moderator)."""
    from ctf.services.event import actor_has_event_capability

    normalized = normalize_participant_username(username)
    with transaction.atomic():
        participant = _locked_rename_target(participant_id)
        if not actor_has_event_capability(actor, participant.event, "participants"):
            raise CTFValidationError("Only the event organizer may rename this account", code="CTF_PERMISSION_DENIED")
        _apply_username_rename(participant, normalized, actor)
    return participant


def rename_own_participant_username(
    participant_id: UUID,
    username: str,
    *,
    actor: User | AnonymousUser,
) -> CTFParticipant:
    """Rename the actor's own participant account (#1593), audited like the organizer path."""
    normalized = normalize_participant_username(username)
    with transaction.atomic():
        participant = _locked_rename_target(participant_id)
        if participant.user_id != actor.pk:
            raise CTFValidationError("You may only change your own username", code="CTF_PERMISSION_DENIED")
        _apply_username_rename(participant, normalized, actor)
    return participant


@sensitive_variables("password")
def reset_participant_credentials(participant_id: UUID) -> CTFParticipant:
    """Reset to the event bootstrap password and optionally deliver it."""
    with transaction.atomic():
        try:
            participant = (
                CTFParticipant.objects.select_for_update(of=("self",))
                .select_related("event", "user")
                .get(pk=participant_id, deleted_at__isnull=True)
            )
        except CTFParticipant.DoesNotExist:
            raise CTFNotFoundError("Participant not found", details={"participant_id": str(participant_id)}) from None
        if participant.user is None or not participant.user.profile.is_ctf_account:
            raise CTFValidationError("Participant has no account", code="CTF_ACCOUNT_REQUIRED")
        password = effective_bootstrap_password(participant.event)
        participant.user.set_password(password)
        participant.user.save(update_fields=["password"])
        from management.services import set_ctf_password_change_required
        from shared.api_tokens.models import ApiToken

        set_ctf_password_change_required(participant.user, True)
        ApiToken.objects.filter(created_by=participant.user, revoked_at__isnull=True).update(revoked_at=timezone.now())

    if participant.email:
        from django.utils.html import escape

        from ctf.services.notification import _build_ctf_login_url, _send_email

        login_url = _build_ctf_login_url()
        username = participant.user.username
        _send_email(
            recipient=participant.email,
            subject=f"CTF login for {participant.event.name}",
            html_content=f"<p>Username: {escape(username)}</p><p>Login: {escape(login_url)}</p>",
            text_content=f"Username: {username}\nLogin: {login_url}",
        )
        _send_email(
            recipient=participant.email,
            subject=f"CTF password for {participant.event.name}",
            # The credential is operator-controlled (event override or configured
            # platform value, issue #1665), so escape it before HTML interpolation.
            html_content=f"<p>Password: {escape(password)}</p>",
            text_content=f"Password: {password}",
        )
    return participant


def anonymize_participant_account(participant_id: UUID) -> bool:
    """Disable and anonymize one temporary account while retaining ownership."""
    with transaction.atomic():
        try:
            participant = (
                CTFParticipant.objects.select_for_update(of=("self",))
                .select_related("user", "user__profile")
                .get(pk=participant_id)
            )
        except CTFParticipant.DoesNotExist:
            return False
        user = participant.user
        if user is None or not user.profile.is_ctf_account:
            return False
        now = timezone.now()
        user.username = f"ctf-tombstone-{user.pk}-{secrets.token_hex(4)}"
        user.email = ""
        user.first_name = ""
        user.last_name = ""
        user.is_active = False
        user.is_staff = False
        user.is_superuser = False
        user.set_unusable_password()
        user.save(
            update_fields=[
                "username",
                "email",
                "first_name",
                "last_name",
                "is_active",
                "is_staff",
                "is_superuser",
                "password",
            ]
        )
        user.groups.clear()
        profile = user.profile
        profile.cognito_sub = None
        profile.issuer = ""
        profile.active_ctf_event_id = None
        profile.must_change_password = False
        profile.deleted_at = now
        profile.anonymized_at = now
        profile.save(
            update_fields=[
                "cognito_sub",
                "issuer",
                "active_ctf_event_id",
                "must_change_password",
                "deleted_at",
                "anonymized_at",
            ]
        )
        participant.email = ""
        participant.save(update_fields=["email", "updated_at"])
        from shared.api_tokens.models import ApiToken

        ApiToken.objects.filter(created_by=user, revoked_at__isnull=True).update(revoked_at=now)
    return True


def purge_expired_participant_accounts() -> int:
    """Anonymize marked accounts whose event retention period elapsed."""
    from datetime import timedelta

    retention = max(0, int(getattr(settings, "CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS", 24)))
    cutoff = timezone.now() - timedelta(hours=retention)
    participant_ids = list(
        CTFParticipant.objects.filter(
            user__profile__is_ctf_account=True,
            user__profile__anonymized_at__isnull=True,
            event__event_end__lte=cutoff,
        ).values_list("pk", flat=True)
    )
    return sum(anonymize_participant_account(participant_id) for participant_id in participant_ids)


def _eligible_ctf_user(user: User | AnonymousUser) -> User | None:
    """Return a concrete user only when its account boundary is intact."""
    eligible_user = None
    profile = None
    if isinstance(user, User) and user.is_active:
        with suppress(AttributeError, ObjectDoesNotExist):
            profile = user.profile
        if profile is not None:
            has_account_marker = profile.is_ctf_account and profile.user_type == "ctf_participant"
            has_safe_permissions = not user.is_staff and not user.is_superuser
            has_exact_group = set(user.groups.values_list("name", flat=True)) == {CTF_PARTICIPANT_GROUP}
            if all((has_account_marker, has_safe_permissions, has_exact_group)):
                eligible_user = user
    return eligible_user


def live_participant_for_user(user: User | AnonymousUser) -> CTFParticipant | None:
    """Return the sole live participation admitted for a temporary account."""
    concrete_user = _eligible_ctf_user(user)
    if concrete_user is None:
        return None

    now = timezone.now()
    matches = list(
        CTFParticipant.objects.select_related("event")
        .filter(
            user=concrete_user,
            deleted_at__isnull=True,
            event__status__in=["active", "paused"],
            event__event_start__lte=now,
            event__event_end__gt=now,
        )
        # CTF-609: disqualified participants keep login (view-only access);
        # CTF-605: banned participants lose event access entirely.
        .exclude(status=ParticipantStatus.BANNED.value)[:2]
    )
    return matches[0] if len(matches) == 1 else None
