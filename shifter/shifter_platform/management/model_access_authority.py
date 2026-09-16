"""Identity-owned authority services for model-access sharing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser, Group
from django.db import transaction

from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.model_access import AuthorityInvalidation, AuthorityState, OwnedReference
from shared.model_access.authority_port import invalidate_authority

from .models import ModelAccessGroupEligibility


def is_platform_operator(user: object | None) -> bool:
    """Return the single active, non-temporary deployment-operator predicate.

    Django staff/model permissions, groups, provider claims, tenancy roles, and
    CTF delegation do not satisfy this global authority.
    """
    from shared.auth import is_temporary_ctf_account

    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_active", False) or not getattr(user, "is_superuser", False):
        return False
    return not is_temporary_ctf_account(cast(AbstractBaseUser | AnonymousUser, user))


class ModelAccessIdentityAuthorityError(Exception):
    """Opaque identity-selector denial with a stable safe code."""

    def __init__(self, code: str = "identity.model_access_denied") -> None:
        self.code = code
        super().__init__("Model-access identity authority denied")


@dataclass(frozen=True, slots=True)
class ModelAccessGroupScope:
    """Canonical direct membership and explicit funded-eligibility projection."""

    group_id: int
    user_ids: tuple[int, ...]
    eligibility_basis: str | None
    eligibility_revision: int | None


@dataclass(frozen=True, slots=True)
class ModelAccessGroupEligibilityView:
    """Revision-fenced result of an eligibility policy mutation."""

    group_id: int
    managed_membership: bool
    spending_approved: bool
    revision: int


def _is_positive_int(value: object) -> bool:
    """Return whether a value is a positive integer but not a boolean."""
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _require_platform_operator(actor: object) -> None:
    """Reject actors without global deployment-operator authority."""
    if not is_platform_operator(actor):
        raise ModelAccessIdentityAuthorityError()


def _locked_group(group_id: int) -> Group:
    """Lock and return one exact auth group without exposing absence details."""
    group = Group.objects.select_for_update().filter(pk=group_id).first()
    if group is None:
        raise ModelAccessIdentityAuthorityError()
    return group


def _eligibility_basis(policy: ModelAccessGroupEligibility | None) -> str | None:
    """Return the explicit funded-access basis supplied by a group policy."""
    basis = None
    if policy is not None and policy.managed_membership:
        basis = "managed_membership"
    elif policy is not None and policy.spending_approved:
        basis = "approved_spending"
    return basis


def resolve_model_access_group(actor: object, group_id: int) -> ModelAccessGroupScope:
    """Resolve one auth-group primary key to active direct members under lock."""
    _require_platform_operator(actor)
    if not _is_positive_int(group_id):
        raise ModelAccessIdentityAuthorityError()
    with transaction.atomic():
        group = _locked_group(group_id)
        user_ids = tuple(
            group.user_set.filter(is_active=True, profile__deleted_at__isnull=True)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        policy = ModelAccessGroupEligibility.objects.select_for_update().filter(group=group).first()
        basis = _eligibility_basis(policy)
        return ModelAccessGroupScope(
            group_id=group.pk,
            user_ids=user_ids,
            eligibility_basis=basis,
            eligibility_revision=policy.revision if policy is not None and basis is not None else None,
        )


def _normalized_user_ids(user_ids: tuple[int, ...]) -> tuple[int, ...]:
    """Validate explicit user identifiers and return canonical ordering."""
    normalized = tuple(sorted(user_ids))
    invalid = (
        not normalized
        or len(normalized) > 1000
        or len(normalized) != len(set(normalized))
        or any(not _is_positive_int(value) for value in normalized)
    )
    if invalid:
        raise ModelAccessIdentityAuthorityError()
    return normalized


def resolve_model_access_users(actor: object, user_ids: tuple[int, ...]) -> tuple[int, ...]:
    """Lock active identities authorized for an operator or self-service selector."""
    normalized = _normalized_user_ids(user_ids)
    actor_id = getattr(actor, "pk", None)
    if not is_platform_operator(actor) and (len(normalized) != 1 or normalized[0] != actor_id):
        raise ModelAccessIdentityAuthorityError()

    users = get_user_model().objects
    with transaction.atomic():
        resolved = tuple(
            users.select_for_update(of=("self",))
            .filter(pk__in=normalized, is_active=True, profile__deleted_at__isnull=True)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        if resolved != normalized:
            raise ModelAccessIdentityAuthorityError()
        return resolved


def _validate_eligibility_input(
    group_id: int,
    *,
    managed_membership: bool,
    spending_approved: bool,
    expected_revision: int,
) -> None:
    """Validate an eligibility mutation without leaking group existence."""
    invalid_revision = (
        isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0
    )
    invalid_flags = not isinstance(managed_membership, bool) or not isinstance(spending_approved, bool)
    if not _is_positive_int(group_id) or invalid_revision or invalid_flags:
        raise ModelAccessIdentityAuthorityError()


def _eligibility_view(policy: ModelAccessGroupEligibility) -> ModelAccessGroupEligibilityView:
    """Project one persisted eligibility policy to the public scalar view."""
    return ModelAccessGroupEligibilityView(
        group_id=policy.group_id,
        managed_membership=policy.managed_membership,
        spending_approved=policy.spending_approved,
        revision=policy.revision,
    )


def _persist_eligibility(
    group: Group,
    policy: ModelAccessGroupEligibility | None,
    *,
    managed_membership: bool,
    spending_approved: bool,
    next_revision: int,
) -> ModelAccessGroupEligibility:
    """Create or advance one locked group eligibility revision."""
    if policy is None:
        return ModelAccessGroupEligibility.objects.create(
            group=group,
            managed_membership=managed_membership,
            spending_approved=spending_approved,
            revision=next_revision,
        )
    policy.managed_membership = managed_membership
    policy.spending_approved = spending_approved
    policy.revision = next_revision
    policy.save(update_fields=["managed_membership", "spending_approved", "revision", "updated_at"])
    return policy


def _record_eligibility_change(
    actor: object,
    policy: ModelAccessGroupEligibility,
) -> None:
    """Invalidate and audit one committed eligibility revision."""
    invalidate_authority(
        AuthorityInvalidation(
            deployment_id=None,
            authority_refs=(OwnedReference(owner="management", reference=f"auth-group:{policy.group_id}"),),
            state=AuthorityState.UNKNOWN,
            reason="group-eligibility-changed",
        )
    )
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.SHARING_BINDING,
            entity_id=policy.group_id,
            action=AuditAction.SHARING_MEMBERSHIP,
            actor_type=AuditActorType.USER,
            actor_id=getattr(actor, "pk", None),
            new_state={
                "managed_membership": policy.managed_membership,
                "spending_approved": policy.spending_approved,
                "revision": policy.revision,
            },
            context="model access group eligibility",
        ),
        strict=True,
    )


def set_model_access_group_eligibility(
    actor: object,
    group_id: int,
    *,
    managed_membership: bool,
    spending_approved: bool,
    expected_revision: int,
) -> ModelAccessGroupEligibilityView:
    """Set explicit group-funded eligibility under an optimistic revision fence."""
    _require_platform_operator(actor)
    _validate_eligibility_input(
        group_id,
        managed_membership=managed_membership,
        spending_approved=spending_approved,
        expected_revision=expected_revision,
    )

    with transaction.atomic():
        group = _locked_group(group_id)
        policy = ModelAccessGroupEligibility.objects.select_for_update().filter(group=group).first()
        current = policy.revision if policy is not None else 0
        if expected_revision != current:
            raise ModelAccessIdentityAuthorityError("identity.group_eligibility_revision_conflict")
        if policy is not None and (
            policy.managed_membership,
            policy.spending_approved,
        ) == (managed_membership, spending_approved):
            return _eligibility_view(policy)

        policy = _persist_eligibility(
            group,
            policy,
            managed_membership=managed_membership,
            spending_approved=spending_approved,
            next_revision=current + 1,
        )
        _record_eligibility_change(actor, policy)
        return _eligibility_view(policy)
