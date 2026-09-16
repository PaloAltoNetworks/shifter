"""Defense-in-depth identity mutation fencing for model-access sharing.

Owner services issue the primary synchronous command themselves.  These
signals cover Django admin, reverse M2M, group deletion, and direct user saves
that bypass those services.  The shared guard prevents a primary service from
double-advancing the same revision.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Model
from django.db.models.signals import m2m_changed, post_save, pre_delete, pre_save

from shared.model_access import AuthorityInvalidation, AuthorityState, OwnedReference
from shared.model_access.authority_port import (
    authority_invalidation_signals_suppressed,
    invalidate_authority,
)

_PREVIOUS_FLAGS = "_model_access_previous_authority_flags"
_CLEARED_GROUPS = "_model_access_cleared_group_ids"


def _invalidate_group_ids(group_ids: set[int]) -> None:
    """Invalidate group authority revisions in bounded batches."""
    if not group_ids:
        return
    ordered = sorted(group_ids)
    for offset in range(0, len(ordered), 64):
        invalidate_authority(
            AuthorityInvalidation(
                deployment_id=None,
                authority_refs=tuple(
                    OwnedReference(owner="management", reference=f"auth-group:{group_id}")
                    for group_id in ordered[offset : offset + 64]
                ),
                state=AuthorityState.UNKNOWN,
                reason="group-membership-changed",
            )
        )


def _capture_user_flags(sender: type[Model], instance: Model, **_kwargs: object) -> None:
    """Capture persisted account authority flags before saving."""
    if authority_invalidation_signals_suppressed() or instance.pk is None:
        return
    previous = sender._default_manager.filter(pk=instance.pk).values_list("is_active", "is_superuser").first()
    setattr(instance, _PREVIOUS_FLAGS, previous)


def _invalidate_user_flags(sender: type[Model], instance: Model, created: bool, **_kwargs: object) -> None:
    """Invalidate user and operator authority after account flag changes."""
    if created or authority_invalidation_signals_suppressed():
        return
    previous = getattr(instance, _PREVIOUS_FLAGS, None)
    is_active = bool(getattr(instance, "is_active", False))
    current = (is_active, bool(getattr(instance, "is_superuser", False)))
    if previous is None or previous == current:
        return
    invalidate_authority(
        AuthorityInvalidation(
            deployment_id=None,
            authority_refs=(
                OwnedReference(owner="management", reference=f"operator:{instance.pk}"),
                OwnedReference(owner="management", reference=f"user:{instance.pk}"),
            ),
            state=AuthorityState.UNKNOWN if is_active else AuthorityState.REVOKED,
            reason="user-authority-changed",
        )
    )


def _group_ids_for_change(instance: Model, reverse: bool, pk_set: set[int] | None) -> set[int]:
    """Resolve group IDs from either side of a membership mutation."""
    if reverse:
        return {instance.pk} if isinstance(instance, Group) and instance.pk is not None else set()
    return set(pk_set or ())


def _groups_changed(
    sender: object,
    instance: Model,
    action: str,
    reverse: bool,
    pk_set: set[int] | None = None,
    **_kwargs: object,
) -> None:
    """Lock before, then invalidate after, direct group membership changes."""
    if not authority_invalidation_signals_suppressed():
        if action == "pre_clear":
            group_ids = (
                {instance.pk}
                if reverse
                else set(
                    instance.groups.values_list("pk", flat=True)  # type: ignore[attr-defined]
                )
            )
            if not reverse:
                setattr(instance, _CLEARED_GROUPS, group_ids)
            tuple(Group.objects.select_for_update().filter(pk__in=group_ids).order_by("pk"))
        elif action in {"pre_add", "pre_remove"}:
            group_ids = _group_ids_for_change(instance, reverse, pk_set)
            tuple(Group.objects.select_for_update().filter(pk__in=group_ids).order_by("pk"))
        elif action in {"post_add", "post_remove", "post_clear"}:
            group_ids = _group_ids_for_change(instance, reverse, pk_set)
            if action == "post_clear" and not reverse:
                group_ids = set(getattr(instance, _CLEARED_GROUPS, set()))
            _invalidate_group_ids(group_ids)


def _group_deleted(sender: type[Group], instance: Group, **_kwargs: object) -> None:
    """Invalidate group authority before group deletion."""
    if authority_invalidation_signals_suppressed() or instance.pk is None:
        return
    _invalidate_group_ids({instance.pk})


def register_model_access_authority_signals() -> None:
    """Connect identity fallback fencing once from the composition root."""
    user_model = get_user_model()
    pre_save.connect(
        _capture_user_flags,
        sender=user_model,
        dispatch_uid="model_access_capture_user_authority",
    )
    post_save.connect(
        _invalidate_user_flags,
        sender=user_model,
        dispatch_uid="model_access_invalidate_user_authority",
    )
    m2m_changed.connect(
        _groups_changed,
        sender=user_model.groups.through,
        dispatch_uid="model_access_invalidate_group_membership",
    )
    pre_delete.connect(
        _group_deleted,
        sender=Group,
        dispatch_uid="model_access_invalidate_group_delete",
    )
