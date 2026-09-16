"""User account lifecycle state machine and transition service (PLAT-236, #1943).

One locked service owns account lifecycle. ``User.is_active`` remains the sole
authentication-enforcement bit; ``UserProfile.suspended_at`` is the only added
discriminator. The administrator-facing state (active / suspended / deactivated /
deleted) is *derived* from durable facts rather than stored as a second enum
that could disagree with ``is_active``.

A transition locks the user and profile rows, derives the current state,
validates a closed transition, updates ``is_active`` and the suspension marker
together, revokes the target's live API tokens as defense in depth for a
disabling action, and writes one request-attributed strict ``shared.audit``
event in the same transaction (audit failure rolls the state change back).
Repeating the current state is an idempotent no-op that does not claim a
transition occurred.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from management import password_reset
from management.models import UserProfile
from management.services import USER_PK_REQUIRED_MSG, AuditContext, safe_user_profile
from shared.api_tokens.models import ApiToken
from shared.audit import AuditAction, AuditEntityType, AuditEvent, audit_log
from shared.constants import USER_CANNOT_BE_NONE
from shared.model_access import AuthorityInvalidation, AuthorityState, OwnedReference
from shared.model_access.authority_port import invalidate_authority, suppress_authority_invalidation_signals

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class AccountLifecycleState(StrEnum):
    """Derived administrator-facing account lifecycle state."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    DELETED = "deleted"


class AccountLifecycleAction(StrEnum):
    """Closed set of administrator-driven lifecycle transitions."""

    ACTIVATE = "activate"
    DEACTIVATE = "deactivate"
    SUSPEND = "suspend"
    DELETE = "delete"


class AccountLifecycleError(Exception):
    """A rejected lifecycle transition carrying a stable, safe error code.

    ``code`` is a bounded, target-agnostic identifier the HTTP layer maps to a
    stable API error code; ``message`` is a safe, human-readable summary that
    never carries identity-binding facts, credentials, or SQL/provider text.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# Closed transition table: for each action, the set of *source* states from
# which it performs a real change. A source state absent from the mapping (other
# than the action's own target state, handled as an idempotent no-op) is an
# invalid transition.
_VALID_SOURCES: dict[AccountLifecycleAction, frozenset[AccountLifecycleState]] = {
    AccountLifecycleAction.ACTIVATE: frozenset({AccountLifecycleState.SUSPENDED, AccountLifecycleState.DEACTIVATED}),
    AccountLifecycleAction.DEACTIVATE: frozenset({AccountLifecycleState.ACTIVE, AccountLifecycleState.SUSPENDED}),
    AccountLifecycleAction.SUSPEND: frozenset({AccountLifecycleState.ACTIVE, AccountLifecycleState.DEACTIVATED}),
    AccountLifecycleAction.DELETE: frozenset(
        {AccountLifecycleState.ACTIVE, AccountLifecycleState.SUSPENDED, AccountLifecycleState.DEACTIVATED}
    ),
}

# The lifecycle state each action targets, used to recognise an idempotent
# no-op (already in the target state).
_ACTION_TARGET_STATE: dict[AccountLifecycleAction, AccountLifecycleState] = {
    AccountLifecycleAction.ACTIVATE: AccountLifecycleState.ACTIVE,
    AccountLifecycleAction.DEACTIVATE: AccountLifecycleState.DEACTIVATED,
    AccountLifecycleAction.SUSPEND: AccountLifecycleState.SUSPENDED,
    AccountLifecycleAction.DELETE: AccountLifecycleState.DELETED,
}

# Actions that block authentication (target's live tokens are revoked).
_DISABLING_ACTIONS = frozenset(
    {AccountLifecycleAction.DEACTIVATE, AccountLifecycleAction.SUSPEND, AccountLifecycleAction.DELETE}
)


def derive_lifecycle_state(user: User) -> AccountLifecycleState:
    """Derive the administrator-facing lifecycle state from durable facts.

    Precedence: a soft-deleted profile is ``deleted`` regardless of the
    authentication bit; otherwise a suspension marker means ``suspended``; a
    cleared authentication bit without a suspension marker means
    ``deactivated``; else ``active``.
    """
    profile = safe_user_profile(user)
    if profile is not None and profile.deleted_at is not None:
        return AccountLifecycleState.DELETED
    if profile is not None and profile.suspended_at is not None:
        return AccountLifecycleState.SUSPENDED
    return AccountLifecycleState.ACTIVE if user.is_active else AccountLifecycleState.DEACTIVATED


def _is_anonymized(user: User) -> bool:
    """Return whether the user's profile carries an anonymization marker."""
    profile = safe_user_profile(user)
    return profile is not None and profile.anonymized_at is not None


def _active_superuser_count() -> int:
    """Return the number of currently active superusers."""
    return get_user_model().objects.filter(is_superuser=True, is_active=True).count()


def _guard_self_action(user: User, action: AccountLifecycleAction, actor: User | None) -> None:
    """Forbid an actor from suspending, deactivating, or deleting their own account."""
    if action in _DISABLING_ACTIONS and actor is not None and actor.pk == user.pk:
        raise AccountLifecycleError(
            "self_action_forbidden", "You cannot suspend, deactivate, or delete your own account."
        )


def _guard_superuser_target(user: User, actor: User | None) -> None:
    """Forbid a non-superuser from changing a superuser account's lifecycle state."""
    if user.is_superuser and not (actor is not None and actor.is_superuser):
        raise AccountLifecycleError(
            "superuser_protected", "Only a superuser may change the lifecycle state of a superuser account."
        )


def _guard_last_active_superuser(user: User, action: AccountLifecycleAction) -> None:
    """Forbid a disabling action that would remove the last active superuser (fast-fail hint)."""
    if action in _DISABLING_ACTIONS and user.is_superuser and user.is_active and _active_superuser_count() <= 1:
        raise AccountLifecycleError("last_superuser_protected", "You cannot disable the last active superuser.")


def _guard_transition(user: User, action: AccountLifecycleAction, actor: User | None) -> None:
    """Raise :class:`AccountLifecycleError` when the transition is forbidden.

    Guards independent of the current state: self-disable is forbidden; a
    non-superuser may not mutate a superuser; a disabling action must never
    strand the deployment without an active superuser.
    """
    _guard_self_action(user, action, actor)
    _guard_superuser_target(user, actor)
    _guard_last_active_superuser(user, action)


def _validate_state(action: AccountLifecycleAction, current: AccountLifecycleState) -> bool:
    """Return True when a real change is needed; False for an idempotent no-op.

    Raises :class:`AccountLifecycleError` for an invalid transition, including an
    attempt to activate a deleted or anonymized account.
    """
    if current == _ACTION_TARGET_STATE[action]:
        return False
    if current == AccountLifecycleState.DELETED:
        raise AccountLifecycleError(
            "account_deleted", "A deleted account cannot change lifecycle state; it must be restored separately."
        )
    if current not in _VALID_SOURCES[action]:
        raise AccountLifecycleError(
            "invalid_transition", f"Cannot {action.value} an account in the {current.value} state."
        )
    return True


def _revoke_live_tokens(user: User) -> int:
    """Revoke every live API token owned by ``user``; return the count revoked."""
    return ApiToken.objects.filter(created_by=user, revoked_at__isnull=True).update(revoked_at=timezone.now())


def _recheck_locked_invariants(locked_user: User, profile: UserProfile, action: AccountLifecycleAction) -> None:
    """Re-check terminal + last-active-superuser invariants under the row lock.

    An anonymized account is terminal (issue #1943 review F3). Locking the whole
    active-superuser set serializes concurrent disables of *different* superusers,
    so two requests cannot both observe two actives and each disable one (review
    F1); the pre-transaction guard is only a fast-fail hint.
    """
    if profile.anonymized_at is not None:
        raise AccountLifecycleError("account_anonymized", "An anonymized account cannot change lifecycle state.")
    if action in _DISABLING_ACTIONS and locked_user.is_superuser and locked_user.is_active:
        active_superuser_ids = list(
            get_user_model()
            .objects.select_for_update()
            .filter(is_superuser=True, is_active=True)
            .values_list("id", flat=True)
        )
        if len(active_superuser_ids) <= 1:
            raise AccountLifecycleError("last_superuser_protected", "You cannot disable the last active superuser.")


def _apply_lifecycle_action(action: AccountLifecycleAction, locked_user: User, profile: UserProfile) -> None:
    """Apply the durable field changes for one lifecycle action under lock.

    ``User.is_active`` is the sole authentication bit; only ``suspend`` sets the
    suspension marker and only ``delete`` sets the deletion marker, while
    ``activate``/``deactivate`` clear the suspension marker so it cannot be
    misreported.
    """
    locked_user.is_active = action == AccountLifecycleAction.ACTIVATE
    locked_user.save(update_fields=["is_active"])
    if action == AccountLifecycleAction.SUSPEND:
        profile.suspended_at = timezone.now()
        profile.save(update_fields=["suspended_at"])
    elif action == AccountLifecycleAction.DELETE:
        profile.deleted_at = timezone.now()
        profile.save(update_fields=["deleted_at"])
    else:
        profile.suspended_at = None
        profile.save(update_fields=["suspended_at"])


def available_actions(user: User, actor: User | None) -> list[str]:
    """Return the server-derived lifecycle actions ``actor`` may take on ``user``.

    Advisory presentation hints for the SPA; every endpoint reauthorizes. Mirrors
    the transition guards so a hint never advertises an action the service will
    reject, and includes ``reset_password`` and ``transfer_ownership`` where
    applicable.
    """
    state = derive_lifecycle_state(user)
    actions: list[str] = []
    if state != AccountLifecycleState.DELETED and not _is_anonymized(user):
        for action in AccountLifecycleAction:
            if state not in _VALID_SOURCES[action]:
                # No real change from the current state (target state or invalid source).
                continue
            try:
                _guard_transition(user, action, actor)
            except AccountLifecycleError:
                continue
            actions.append(action.value)
    eligible, _reason = password_reset.reset_eligibility(user)
    if eligible:
        actions.append("reset_password")
    # Ownership transfer is a superuser-only offboarding action (#1943 review F5).
    if actor is not None and actor.pk != user.pk and getattr(actor, "is_superuser", False):
        actions.append("transfer_ownership")
    return actions


def transition_account(
    user: User,
    *,
    action: AccountLifecycleAction,
    actor: User,
    audit: AuditContext,
) -> AccountLifecycleState:
    """Apply a lifecycle ``action`` to ``user`` under lock, atomically audited.

    Returns the resulting derived state. A no-op (already in the target state)
    returns that state without writing an audit row or claiming a transition.

    Raises:
        TypeError: If user is None.
        ValueError: If user has no primary key (unsaved).
        AccountLifecycleError: If the transition is forbidden or invalid.
    """
    if user is None:
        raise TypeError(USER_CANNOT_BE_NONE)
    if user.pk is None:
        raise ValueError(USER_PK_REQUIRED_MSG)

    _guard_transition(user, action, actor)

    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        profile, _created = UserProfile.objects.select_for_update().get_or_create(user=locked_user)
        # Keep the in-memory profile attached so derive_lifecycle_state reads the
        # locked row rather than issuing another query.
        locked_user.profile = profile
        current = derive_lifecycle_state(locked_user)

        _recheck_locked_invariants(locked_user, profile, action)

        if not _validate_state(action, current):
            logger.info("Lifecycle no-op action=%s state=%s user_id=%s", action.value, current.value, locked_user.id)
            return current

        previous_active = locked_user.is_active
        previous_state = current

        with suppress_authority_invalidation_signals():
            _apply_lifecycle_action(action, locked_user, profile)
        revoked = _revoke_live_tokens(locked_user) if action in _DISABLING_ACTIONS else 0
        new_state = derive_lifecycle_state(locked_user)
        invalidate_authority(
            AuthorityInvalidation(
                deployment_id=None,
                authority_refs=(
                    OwnedReference(owner="management", reference=f"operator:{locked_user.pk}"),
                    OwnedReference(owner="management", reference=f"user:{locked_user.pk}"),
                ),
                state=(AuthorityState.REVOKED if action in _DISABLING_ACTIONS else AuthorityState.UNKNOWN),
                reason=f"user-{action.value}",
            )
        )
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.USER,
                entity_id=locked_user.id,
                action=AuditAction.DELETE if action == AccountLifecycleAction.DELETE else AuditAction.UPDATE,
                actor_type=audit.actor_type,
                actor_id=audit.actor_id,
                previous_state={"lifecycle_state": previous_state.value, "is_active": previous_active},
                new_state={"lifecycle_state": new_state.value, "is_active": locked_user.is_active},
                context=f"account lifecycle {action.value}",
                request_id=audit.request_id,
                source_ip=audit.source_ip,
                user_agent=audit.user_agent,
            ),
            strict=True,
        )

    logger.info(
        "Lifecycle transition action=%s from=%s to=%s tokens_revoked=%s user_id=%s",
        action.value,
        previous_state.value,
        new_state.value,
        revoked,
        locked_user.id,
    )
    # Reflect the committed change on the caller's instance.
    user.is_active = locked_user.is_active
    return new_state
