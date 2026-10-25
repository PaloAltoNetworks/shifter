"""Tenant administration over verified catalog packs and Engine plugin bindings."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q

from cms.models import RaesPackageSource
from cms.scenarios.catalog_presentation import list_catalog_presentations
from cms.scenarios.realizability import _availability_provider, _trusted_scenario_path
from engine.services import RuntimePluginPackView, bind_runtime_plugin, list_runtime_plugin_bindings
from shared.audit import RequestAudit
from shared.exceptions import ValidationError
from shared.raes.realizability import RealizabilityOutcome, assess_scenario_capability
from shared.runtime_plugin_binding import PluginTargetBindings, RuntimePluginScope
from workspaces.services import get_organization_profile


def list_runtime_plugin_packs(user: User, organization_uuid: UUID) -> list[dict[str, Any]]:
    """List verified packs visible to an authorized organization administrator."""
    get_organization_profile(user, organization_uuid)
    bindings = {row.pack_id: row for row in list_runtime_plugin_bindings(user, organization_uuid)}
    available = dict(
        RaesPackageSource.objects.filter(
            Q(organization_uuid=organization_uuid) | Q(organization_uuid__isnull=True),
        ).values_list("scenario_id", "organization_uuid")
    )
    packs = []
    for entry in list_catalog_presentations(user=user):
        if entry["id"] not in available:
            continue
        evidence = entry.get("raes")
        if evidence is None:
            continue
        binding = bindings.get(entry["id"])
        packs.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "pack_digest": evidence["package_digest"],
                "can_update": available[entry["id"]] == organization_uuid,
                "binding": asdict(binding) if binding is not None else None,
            }
        )
    return sorted(packs, key=lambda row: row["id"])


def runtime_plugin_pack_detail(user: User, organization_uuid: UUID, pack_id: str) -> dict[str, Any]:
    """Return selectable guest identities only; never apply a compiled plan."""
    entry = next((row for row in list_runtime_plugin_packs(user, organization_uuid) if row["id"] == pack_id), None)
    if entry is None:
        raise ValidationError("The pack is unavailable")
    source = RaesPackageSource.objects.filter(scenario_id=pack_id).first()
    if source is None:
        raise ValidationError("The pack is unavailable")
    with _trusted_scenario_path(source) as (path, _gap):
        if path is None:
            raise ValidationError("The registered pack could not be verified; reinstall the pack before binding")
        assessment = assess_scenario_capability(path, artifact_availability_provider=_availability_provider("gce"))
    if assessment.outcome == RealizabilityOutcome.INDETERMINATE:
        raise ValidationError("The pack's guest targets could not be resolved")
    # Bind to the exact source row whose bytes were verified, not an earlier list
    # projection if catalog registration changed while it was being loaded.
    entry["pack_digest"] = source.package_digest
    return {
        **entry,
        "targets": [{"address": row.address, "os_family": row.os_family} for row in assessment.image_demands],
    }


def set_runtime_plugin_pack(
    user: User,
    organization_uuid: UUID,
    pack_id: str,
    payload: dict[str, Any],
    *,
    audit: RequestAudit | None = None,
) -> RuntimePluginPackView:
    """Bind a verified pack revision to an administrator-selected installation."""
    detail = runtime_plugin_pack_detail(user, organization_uuid, pack_id)
    if payload["pack_digest"] != detail["pack_digest"]:
        raise ValidationError("The pack changed; reload its current version before saving")
    try:
        bindings = PluginTargetBindings.model_validate(payload["bindings"])
        if not set(bindings.targets.values()) <= {row["address"] for row in detail["targets"]}:
            raise ValueError("Unknown guest")
    except ValueError:
        raise ValidationError("Select a pack guest for every required plugin target") from None
    with transaction.atomic():
        source = RaesPackageSource.objects.select_for_update().filter(scenario_id=pack_id).first()
        if source is None or source.package_digest != detail["pack_digest"]:
            raise ValidationError("The pack changed; reload its current version before saving")
        return bind_runtime_plugin(
            user,
            RuntimePluginScope(organization_uuid=organization_uuid, pack_digest=detail["pack_digest"], pack_id=pack_id),
            payload["installation_id"],
            bindings.model_dump(mode="json"),
            enabled=payload["enabled"],
            audit=audit,
        )
