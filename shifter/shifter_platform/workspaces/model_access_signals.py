"""Defense-in-depth model-access fencing for organization authority changes."""

from __future__ import annotations

from django.db import connection
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from shared.model_access import AuthorityInvalidation, AuthorityState, OwnedReference
from shared.model_access.authority_port import invalidate_authority
from workspaces.models import Organization, OrganizationMembership

_PREVIOUS_ORGANIZATION = "_model_access_previous_organization_id"


def _organization_ref(organization_id: int | None) -> OwnedReference | None:
    """Resolve a database identifier to a qualified organization reference."""
    if organization_id is None:
        return None
    organization_uuid = Organization.objects.filter(pk=organization_id).values_list("uuid", flat=True).first()
    if organization_uuid is None:
        return None
    return OwnedReference(owner="workspaces", reference=f"organization:{organization_uuid}")


def _invalidate_organizations(*organization_ids: int | None) -> None:
    """Invalidate unique organization authorities in stable order."""
    refs = tuple(
        reference
        for reference in (
            _organization_ref(value) for value in sorted({item for item in organization_ids if item is not None})
        )
        if reference is not None
    )
    if not refs:
        return
    invalidate_authority(
        AuthorityInvalidation(
            deployment_id=None,
            authority_refs=refs,
            state=AuthorityState.UNKNOWN,
            reason="organization-authority-changed",
        )
    )


@receiver(
    pre_save,
    sender=OrganizationMembership,
    dispatch_uid="workspaces.model_access.organization_membership.capture",
)
def capture_organization_membership(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: object
) -> None:
    """Capture and lock organization authority before membership mutation."""
    previous = None
    if not instance._state.adding:
        previous = sender.objects.filter(pk=instance.pk).values_list("organization_id", flat=True).first()
    setattr(instance, _PREVIOUS_ORGANIZATION, previous)
    organization_ids = sorted({item for item in (previous, instance.organization_id) if item is not None})
    if connection.in_atomic_block:
        tuple(Organization.objects.select_for_update().filter(pk__in=organization_ids).order_by("pk"))


@receiver(
    post_save,
    sender=OrganizationMembership,
    dispatch_uid="workspaces.model_access.organization_membership.invalidate",
)
def invalidate_organization_membership(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: object
) -> None:
    """Invalidate current and prior organizations after membership mutation."""
    _invalidate_organizations(
        getattr(instance, _PREVIOUS_ORGANIZATION, None),
        instance.organization_id,
    )


@receiver(
    pre_delete,
    sender=OrganizationMembership,
    dispatch_uid="workspaces.model_access.organization_membership.delete",
)
def invalidate_deleted_organization_membership(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: object
) -> None:
    """Invalidate the owning organization before membership deletion."""
    if connection.in_atomic_block:
        tuple(Organization.objects.select_for_update().filter(pk=instance.organization_id))
    _invalidate_organizations(instance.organization_id)
