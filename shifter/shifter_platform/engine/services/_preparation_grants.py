"""Cloud-operator grant activation after actual installation readback, never pack input."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.cloud.preparation_cloud_readback import verify_cloud_installation
from shared.cloud.preparation_installation import PreparationInstallation
from shared.cloud.preparation_installation_readback import verify_kubernetes_installation
from shared.exceptions import ValidationError

from ._preparation_adapters import require_preparation_permission

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.models import PreparationGrant


def activate_preparation_grant(
    user: User,
    payload: object,
    *,
    cloud_reader: Callable[[str], dict[str, Any] | None] | None = None,
    kubernetes_reader: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> UUID:
    """CLI-only operator path; cloud observations occur outside the database transaction.

    The application identity cannot grant itself IAM. The installing process must
    independently hold cloud/Kubernetes read access and this application permission.
    Cloud/worker authority changes use a new namespace, leaving old cleanup
    executable. A verified platform-controller release can refresh the proof
    without changing the immutable worker grant or existing operation inputs.
    """
    from engine.models import PreparationGrant, PreparationScopeLock

    require_preparation_permission(user, "manage_preparation_grants")
    try:
        configuration = PreparationInstallation.model_validate(payload)
        cloud_digest = verify_cloud_installation(configuration, cloud_reader)
        kube_digest = verify_kubernetes_installation(configuration, kubernetes_reader)
        if cloud_digest != configuration.digest or kube_digest != configuration.digest:
            raise ValueError("installation proof does not match")
    except ValueError as exc:
        raise ValidationError("Preparation installation verification failed") from exc
    grant = configuration.grant
    with transaction.atomic():
        actor = get_user_model().objects.select_for_update().get(pk=user.pk)
        require_preparation_permission(actor, "manage_preparation_grants")
        PreparationScopeLock.objects.get_or_create(scope_digest=grant.scope_digest)
        PreparationScopeLock.objects.select_for_update().get(pk=grant.scope_digest)
        existing = PreparationGrant.objects.select_for_update().filter(scope_digest=grant.scope_digest)
        if existing.exclude(configuration_digest=grant.digest).exists():
            raise ValidationError("A changed preparation installation requires a new namespace")
        row, _ = PreparationGrant.objects.get_or_create(
            configuration_digest=grant.digest,
            defaults={
                "scope_digest": grant.scope_digest,
                "configuration": grant.model_dump(mode="json"),
                "installation_digest": configuration.digest,
                "installation": configuration.model_dump(mode="json"),
            },
        )
        if row.configuration != grant.model_dump(mode="json"):
            raise ValidationError("The immutable preparation installation has changed")
        previous_digest = row.installation_digest
        proposed = configuration.model_dump(mode="json")
        if row.installation != proposed:
            # The controller is platform software. Upgrading it cannot change
            # cloud identities, isolation, worker images, budgets or input trust.
            previous_authority = {key: value for key, value in row.installation.items() if key != "controller_image"}
            next_authority = {key: value for key, value in proposed.items() if key != "controller_image"}
            if previous_authority != next_authority:
                raise ValidationError("A changed preparation installation requires a new namespace")
            row.installation = proposed
            row.installation_digest = configuration.digest
        row.active = True
        row.verified_at = timezone.now()
        row.save(update_fields=["active", "verified_at", "installation", "installation_digest"])
        _audit_grant(actor, row, previous_digest=previous_digest)
        return row.id


def revoke_preparation_grant(user: User, identity: UUID) -> None:
    """Revoke new execution and admission, preserving pinned cleanup and evidence."""
    from engine.models import PreparationGrant, PreparationScopeLock

    require_preparation_permission(user, "manage_preparation_grants")
    with transaction.atomic():
        initial = PreparationGrant.objects.filter(pk=identity).first()
        if initial is None:
            raise ValidationError("The preparation grant is unavailable")
        PreparationScopeLock.objects.select_for_update().get(pk=initial.scope_digest)
        row = PreparationGrant.objects.select_for_update().get(pk=identity)
        row.active = False
        row.save(update_fields=["active"])
        _audit_grant(user, row)


def _audit_grant(user: User, row: PreparationGrant, *, previous_digest: str = "") -> None:
    """Handle audit grant."""
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.PREPARATION_GRANT,
            entity_id=0,
            entity_ref=str(row.id),
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=user.id,
            previous_state={"installation_digest": previous_digest} if previous_digest else {},
            new_state={"id": str(row.id), "active": row.active, "installation_digest": row.installation_digest},
        ),
        strict=True,
    )
