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
from ctf.models import CTFEvent, CTFParticipant, CTFTeam
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
_PASSWORD_GENERATION_ATTEMPTS = 8
_PASSWORD_BYTES = 24


@sensitive_variables("candidate")
def _validate_participant_password(candidate: str, *, user: User | None = None) -> None:
    """Apply Django's canonical password policy and expose a stable domain error."""
    from django.contrib.auth.password_validation import validate_password

    try:
        validate_password(candidate, user=user)
    except ValidationError as exc:
        raise CTFValidationError(
            "Participant password does not meet the password policy.",
            code="CTF_PARTICIPANT_PASSWORD_INVALID",
        ) from exc


@sensitive_variables("candidate")
def generate_participant_password(*, user: User | None = None) -> str:
    """Return a CSPRNG password accepted by the configured Django validators."""
    for _ in range(_PASSWORD_GENERATION_ATTEMPTS):
        candidate = secrets.token_urlsafe(_PASSWORD_BYTES)
        try:
            _validate_participant_password(candidate, user=user)
        except CTFValidationError:
            continue
        return candidate
    raise CTFValidationError(
        "Unable to generate a compliant participant password.",
        code="CTF_PARTICIPANT_PASSWORD_GENERATION_FAILED",
    )


@sensitive_variables("override")
def _event_shared_participant_password(event: CTFEvent) -> str | None:
    """Return a validated explicit event-shared password, or ``None``."""
    override = getattr(event, "participant_password_override", "") or ""
    if not override.strip():
        return None
    _validate_participant_password(override)
    return override


def _password_for_new_participant(event: CTFEvent) -> str:
    """Select explicit event-shared policy or generated-by-default creation."""
    return _event_shared_participant_password(event) or generate_participant_password()


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
def provision_participant_seat(
    event: CTFEvent,
    *,
    email: str,
    name: str,
    team: CTFTeam | None = None,
) -> CTFParticipant:
    """Create a fresh isolated account and its ``registered`` participation in one step.

    This is the single seam every organizer creation path (single add, CSV
    import, generated seats) converges on. Provisioning is immediate: the
    participation is ``registered`` with a linked isolated account the moment it
    exists — there is no transient ``INVITED`` hop and no invitation awaiting
    acceptance. The caller owns the surrounding ``transaction.atomic()`` block,
    the event/team capacity locks and uniqueness checks, and the single
    post-commit :func:`request_event_provisioning` enqueue.
    """
    password = _password_for_new_participant(event)
    user = _new_user(password, generate_participant_username)
    group, _ = Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)
    user.groups.set([group])
    configure_temporary_ctf_account(user, event.pk)
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        email=email,
        name=name,
        team=team,
        status=ParticipantStatus.REGISTERED.value,
        registered_at=timezone.now(),
    )


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
        for index in range(count):
            participant = provision_participant_seat(
                event,
                email=email.strip().lower() if count == 1 else "",
                name=display_name.strip() or f"Participant {active_count + index + 1}",
            )
            created.append(participant)
        transaction.on_commit(lambda: request_event_provisioning(event.pk, source="participant_accounts"))
    return created


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
    """Anonymize marked accounts whose event retention period elapsed.

    Purging an account also fences that participation's scoped communications
    (coordinate erased, unclaimed delivery stopped), so a purged account leaves no
    deliverable communication behind (#2099, AC3). The communication hook is
    idempotent, so a participant later hard-removed re-runs it harmlessly.
    """
    from datetime import timedelta

    from ctf.services.communication import on_participant_removed

    retention = max(0, int(getattr(settings, "CTF_PARTICIPANT_ACCOUNT_RETENTION_HOURS", 24)))
    cutoff = timezone.now() - timedelta(hours=retention)
    participant_ids = list(
        CTFParticipant.objects.filter(
            user__profile__is_ctf_account=True,
            user__profile__anonymized_at__isnull=True,
            event__event_end__lte=cutoff,
        ).values_list("pk", flat=True)
    )
    purged = 0
    for participant_id in participant_ids:
        # Anonymize and fence communications in ONE transaction per participant, so a
        # crash cannot leave the account anonymized (and thus skipped by the next
        # sweep) while its communications were never fenced (#2099).
        with transaction.atomic():
            if anonymize_participant_account(participant_id):
                purged += 1
                participant = CTFParticipant.objects.filter(pk=participant_id).first()
                if participant is not None:
                    on_participant_removed(participant)
    return purged


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
