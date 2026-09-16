"""Defense-in-depth authority fencing for canonical Engine range mutations."""

from __future__ import annotations

from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from engine.models import Range
from shared.model_access import AuthorityInvalidation, AuthorityState, OwnedReference
from shared.model_access.authority_port import invalidate_authority

_PREVIOUS = "_model_access_range_authority_before"
_FIELDS = ("user_id", "workspace_id", "status", "destroyed_at")


def _references(range_obj: Range, previous: dict[str, object] | None = None) -> tuple[OwnedReference, ...]:
    """Build every authority reference affected by a range mutation."""
    previous = previous or {}
    refs = {
        ("engine", "all-ranges"),
        ("engine", f"range:{range_obj.uuid}"),
        ("management", f"user:{range_obj.user_id}"),
        ("workspaces", f"workspace-id:{range_obj.workspace_id}"),
    }
    if previous.get("user_id") is not None:
        refs.add(("management", f"user:{previous['user_id']}"))
    if previous.get("workspace_id") is not None:
        refs.add(("workspaces", f"workspace-id:{previous['workspace_id']}"))
    return tuple(OwnedReference(owner=owner, reference=reference) for owner, reference in sorted(refs))


def _invalidate(range_obj: Range, previous: dict[str, object] | None = None) -> None:
    """Invalidate current and previous range authority scopes."""
    invalidate_authority(
        AuthorityInvalidation(
            deployment_id=None,
            authority_refs=_references(range_obj, previous),
            state=AuthorityState.UNKNOWN,
            reason="range-authority-changed",
        )
    )


@receiver(pre_save, sender=Range, dispatch_uid="engine.model_access.range.capture")
def capture_range_authority(sender: type[Range], instance: Range, **kwargs: object) -> None:
    """Capture persisted range authority before saving."""
    if instance._state.adding:
        setattr(instance, _PREVIOUS, None)
        return
    setattr(instance, _PREVIOUS, sender.objects.filter(pk=instance.pk).values(*_FIELDS).first())


@receiver(post_save, sender=Range, dispatch_uid="engine.model_access.range.invalidate")
def invalidate_range_authority(sender: type[Range], instance: Range, **kwargs: object) -> None:
    """Invalidate range authority when security-relevant fields change."""
    previous = getattr(instance, _PREVIOUS, None)
    if previous is None or any(previous[field] != getattr(instance, field) for field in _FIELDS):
        _invalidate(instance, previous)


@receiver(pre_delete, sender=Range, dispatch_uid="engine.model_access.range.delete")
def invalidate_deleted_range_authority(sender: type[Range], instance: Range, **kwargs: object) -> None:
    """Invalidate range authority before deletion."""
    _invalidate(instance)
