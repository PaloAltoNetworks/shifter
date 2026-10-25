"""Bind tenant-owned plugins to exact pack digests and retain range selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import transaction
from shifter_adapter_sdk.runtime import PluginManifest, canonical_digest

from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, RequestAudit, audit_log
from shared.exceptions import ValidationError
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimePluginPin, RuntimePluginScope

from ._runtime_plugins import _authorize

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from engine.models import Range, RuntimePluginPackBinding


@dataclass(frozen=True)
class RuntimePluginPackView:
    """Current tenant pack selection and the installation readiness it depends on."""

    id: UUID
    organization_uuid: UUID
    pack_id: str
    pack_digest: str
    installation_id: UUID
    bindings: dict[str, Any]
    enabled: bool
    installation_state: str


def bind_runtime_plugin(
    user: User,
    scope: RuntimePluginScope,
    installation_id: UUID,
    bindings: object,
    *,
    enabled: bool = True,
    audit: RequestAudit | None = None,
) -> RuntimePluginPackView:
    """Authorize and update a pack's selection, without changing any range pin."""
    from engine.models import RuntimePluginInstallation, RuntimePluginPackBinding

    organization_uuid = _authorize(user, scope.organization_uuid)
    pack_id, pack_digest = scope.pack_id, scope.pack_digest
    try:
        RuntimePluginScope(organization_uuid=organization_uuid, pack_id=pack_id, pack_digest=pack_digest)
        parsed = PluginTargetBindings.model_validate(bindings)
    except ValueError:
        raise ValidationError("The pack digest or plugin bindings are invalid") from None
    if not isinstance(enabled, bool):
        raise ValidationError("The binding state is invalid")
    with transaction.atomic():
        installation = (
            RuntimePluginInstallation.objects.select_for_update()
            .filter(
                pk=installation_id,
                organization_uuid=organization_uuid,
            )
            .first()
        )
        if installation is None:
            raise ValidationError("The plugin is unavailable")
        if enabled and installation.state != "ready":
            raise ValidationError("The plugin must pass compatibility checks before binding")
        try:
            manifest = PluginManifest.model_validate(installation.manifest)
            if manifest.digest != installation.manifest_digest:
                raise ValueError("Stored plugin identity mismatch")
            parsed.validate_manifest(manifest)
            RuntimePluginPin(
                installation_id=installation.id,
                organization_uuid=organization_uuid,
                pack_id=pack_id,
                pack_digest=pack_digest,
                manifest=manifest,
                bindings=parsed,
            )
        except ValueError:
            raise ValidationError("The bindings do not match the installed plugin declaration") from None
        row, _ = RuntimePluginPackBinding.objects.update_or_create(
            organization_uuid=organization_uuid,
            pack_id=pack_id,
            defaults={
                "installation": installation,
                "pack_digest": pack_digest,
                "bindings": parsed.model_dump(mode="json"),
                "enabled": enabled,
            },
        )
        attribution = audit or RequestAudit()
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RUNTIME_PLUGIN,
                entity_id=0,
                entity_ref=str(row.id),
                action=AuditAction.UPDATE,
                actor_type=attribution.actor_type or AuditActorType.USER,
                actor_id=attribution.actor_id if attribution.actor_type else user.id,
                request_id=attribution.request_id,
                source_ip=attribution.source_ip,
                user_agent=attribution.user_agent,
                new_state={
                    "organization_uuid": str(organization_uuid),
                    "pack_digest": pack_digest,
                    "installation_id": str(installation.id),
                    "enabled": enabled,
                },
            ),
            strict=True,
        )
        return _view(row)


def list_runtime_plugin_bindings(user: User, organization_uuid: UUID) -> list[RuntimePluginPackView]:
    """List explicit selections owned by the authorized organization."""
    from engine.models import RuntimePluginPackBinding

    organization_uuid = _authorize(user, organization_uuid)
    return [
        _view(row)
        for row in RuntimePluginPackBinding.objects.filter(
            organization_uuid=organization_uuid,
        )
        .select_related("installation")
        .order_by("pack_digest")
    ]


def has_runtime_plugin_binding(organization_uuid: UUID, pack_id: str) -> bool:
    """Whether a trusted launch scope needs cold plugin admission, even if disabled."""
    from engine.models import RuntimePluginPackBinding

    return RuntimePluginPackBinding.objects.filter(
        organization_uuid=organization_uuid,
        pack_id=pack_id,
    ).exists()


def resolve_runtime_plugin_pin(
    scope: RuntimePluginScope, plan: dict[str, Any], *, backend: str | None = None
) -> RuntimePluginPin | None:
    """Resolve under the installation lock held through range creation.

    Called only with the CMS launch boundary's authorized organization, verified
    pack digest and compiled plan, inside the Engine range transaction.
    """
    from engine.models import RuntimePluginInstallation, RuntimePluginPackBinding

    organization_uuid, pack_digest = scope.organization_uuid, scope.pack_digest

    candidate = (
        RuntimePluginPackBinding.objects.filter(
            organization_uuid=organization_uuid,
            pack_id=scope.pack_id,
        )
        .values_list("pk", "installation_id")
        .first()
    )
    if candidate is None:
        return None
    # All writers lock installation before binding. Recheck after acquiring both
    # locks: a concurrent version switch must not admit a partially old pin.
    installation = RuntimePluginInstallation.objects.select_for_update().get(pk=candidate[1])
    binding = RuntimePluginPackBinding.objects.select_for_update().get(pk=candidate[0])
    if binding.installation_id != installation.id:
        raise ValidationError("The pack's runtime plugin changed during launch; retry the launch")
    if binding.pack_digest != pack_digest:
        raise ValidationError("The pack changed; an administrator must bind its new version before launch")
    if not binding.enabled or installation.state != "ready" or installation.organization_uuid != organization_uuid:
        raise ValidationError("The pack's runtime plugin is not enabled and ready")
    try:
        manifest = PluginManifest.model_validate(installation.manifest)
        if manifest.digest != installation.manifest_digest:
            raise ValueError("Stored plugin identity mismatch")
        pin = RuntimePluginPin(
            installation_id=installation.id,
            organization_uuid=organization_uuid,
            pack_id=scope.pack_id,
            pack_digest=pack_digest,
            manifest=manifest,
            bindings=binding.bindings,
        )
        pin.bindings.validate_plan(plan)
        if backend is not None:
            pin.bindings.validate_provider(backend)
        return pin
    except ValueError:
        raise ValidationError("The installed plugin does not match this pack's compiled guests") from None


def persist_runtime_plugin_pin(target: Range, pin: RuntimePluginPin | None) -> None:
    """Retain the admitted installation and guest mapping for the range lifetime."""
    from engine.models import RuntimePluginRangeBinding

    if pin is not None:
        RuntimePluginRangeBinding.objects.create(
            range=target,
            installation_id=pin.installation_id,
            pin=pin.model_dump(mode="json"),
            pin_digest=pin.digest,
        )


def retained_runtime_plugin_pin(target: Range) -> RuntimePluginPin | None:
    """Read the original pin for retries/cleanup even after registry retirement."""
    from engine.models import RuntimePluginRangeBinding

    row = RuntimePluginRangeBinding.objects.filter(range=target).first()
    if row is None:
        return None
    try:
        pin = RuntimePluginPin.model_validate(row.pin)
        # Check the exact retained bytes, not a re-serialized model: adding a
        # defaulted binding field must not make pre-upgrade pins undeletable.
        if canonical_digest(row.pin) != row.pin_digest or pin.installation_id != row.installation_id:
            raise ValueError("Stored pin identity mismatch")
        pin.bindings.validate_plan(target.range_config)
        if target.range_backend:
            pin.bindings.validate_provider(str(target.range_backend))
        return pin
    except ValueError:
        raise ValidationError("The range's runtime plugin binding is invalid") from None


def _view(row: RuntimePluginPackBinding) -> RuntimePluginPackView:
    """Project a stored pack binding and current installation state."""
    bindings = PluginTargetBindings.model_validate(row.bindings).model_dump(mode="json")
    return RuntimePluginPackView(
        row.id,
        row.organization_uuid,
        row.pack_id,
        row.pack_digest,
        row.installation_id,
        bindings,
        row.enabled,
        row.installation.state,
    )
