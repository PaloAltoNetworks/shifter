"""Tenant-managed RAES image registry service (ADR-032-R2).

The single validated write path for :class:`engine.models.RaesImageMapping` -- the
tenant operator surface (and any future management API) goes through this, so
validation and idempotent upsert-by-natural-key live in one place. The provisioner
reads and resolves these rows at realization; it does not use this seam (CQRS: the
platform writes, the provisioner reads).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from shared.raes.artifact_inventory import BackendArtifact

if TYPE_CHECKING:
    from datetime import datetime

    from engine.models import RaesImageMapping

__all__ = [
    "RaesImageMappingError",
    "RaesImageMappingOptions",
    "RaesImageMappingView",
    "disable_raes_image_mapping",
    "list_backend_artifacts",
    "list_raes_image_mappings",
    "upsert_raes_image_mapping",
]


class RaesImageMappingError(ValueError):
    """Raised when an RAES image mapping fails validation."""


@dataclass(frozen=True)
class RaesImageMappingOptions:
    """Optional fields for an RAES image mapping (beyond the natural key + image ref).

    The portable-identity block (``artifact_id`` / ``artifact_digest`` /
    ``media_type`` / ``integrity_ref`` / ``provenance_ref``) binds the mapping to a
    portable RAES ``ArtifactIdentity`` and its admission evidence (#1580). Either
    leave all five blank (a legacy alias-only mapping) or supply all five (a
    portable mapping that can satisfy an authored artifact requirement).
    """

    source_version: str = ""
    machine_type: str = ""
    disk_size_gb: int | None = None
    disk_type: str = ""
    enabled: bool = True
    notes: str = ""
    artifact_id: str = ""
    artifact_version: str = ""
    artifact_digest: str = ""
    media_type: str = ""
    integrity_ref: str = ""
    provenance_ref: str = ""


@dataclass(frozen=True)
class RaesImageMappingView:
    """Allowlisted read projection of an :class:`engine.models.RaesImageMapping` row.

    The list seam shared by the tenant management surfaces (management command +
    CMS API). Keeping the projection here -- beside the write path -- means the
    command and the API render one field allowlist and neither reaches into the
    model directly.
    """

    id: int
    provider: str
    source_name: str
    source_version: str
    image_ref: str
    machine_type: str
    disk_size_gb: int | None
    disk_type: str
    enabled: bool
    notes: str
    artifact_id: str
    artifact_version: str
    artifact_digest: str
    media_type: str
    integrity_ref: str
    provenance_ref: str
    created_at: datetime
    updated_at: datetime


def upsert_raes_image_mapping(
    *,
    provider: str,
    source_name: str,
    image_ref: str,
    options: RaesImageMappingOptions | None = None,
) -> RaesImageMapping:
    """Create or update an RAES image mapping, keyed on (provider, source_name, source_version).

    Idempotent so tenant automation can converge the registry declaratively. A
    blank ``source_version`` registers the any-version fallback. Retire a mapping
    by upserting with ``options.enabled=False`` (preserves audit; realization then
    fails loud) rather than deleting it.
    """
    from engine.models import RaesImageMapping

    opts = options or RaesImageMappingOptions()
    normalized_provider = _normalize_provider(provider)
    name = _require(source_name, field="source_name")
    ref = _require(image_ref, field="image_ref")
    if opts.disk_size_gb is not None and opts.disk_size_gb <= 0:
        raise RaesImageMappingError("disk_size_gb must be a positive integer when set")
    portable = _validate_portable_identity(opts)

    mapping, _created = RaesImageMapping.objects.update_or_create(
        provider=normalized_provider,
        source_name=name,
        source_version=(opts.source_version or "").strip(),
        defaults={
            "image_ref": ref,
            "machine_type": (opts.machine_type or "").strip(),
            "disk_size_gb": opts.disk_size_gb,
            "disk_type": (opts.disk_type or "").strip(),
            "enabled": opts.enabled,
            "notes": opts.notes or "",
            **portable,
        },
    )
    return mapping


def list_raes_image_mappings(
    *,
    provider: str | None = None,
    include_disabled: bool = True,
) -> list[RaesImageMappingView]:
    """Return registry rows as allowlisted DTOs in stable natural-key order.

    Optional ``provider`` filters to one provider (normalized/validated exactly
    like the write path, so an unknown provider raises rather than silently
    returning nothing). ``include_disabled=False`` hides soft-disabled rows the
    way the provisioner resolver ignores them; the default shows them so an
    operator can audit and re-enable.
    """
    from engine.models import RaesImageMapping

    queryset = RaesImageMapping.objects.all().order_by("provider", "source_name", "source_version")
    if provider is not None:
        queryset = queryset.filter(provider=_normalize_provider(provider))
    if not include_disabled:
        queryset = queryset.filter(enabled=True)
    return [_to_view(row) for row in queryset]


def list_backend_artifacts(*, provider: str) -> list[BackendArtifact]:
    """Return the enabled portable-identity registry rows for ``provider`` as backend artifacts.

    Only rows carrying a portable ``ArtifactIdentity`` (a non-blank
    ``artifact_digest``) are backend-owned artifacts the resolution seam can
    satisfy against; legacy alias-only rows resolve the source-name path and never
    satisfy a portable artifact requirement. This is the one projection both the
    catalog realizability contributor and the launch-time fencing resolver consume,
    so they agree on what the backend owns.
    """
    from ._preparation_inventory import mapping_matches_admission, prepared_inventory_facts

    rows = list_raes_image_mappings(provider=provider, include_disabled=False)
    prepared = prepared_inventory_facts([row.id for row in rows])
    result: list[BackendArtifact] = []
    for row in rows:
        facts = prepared.get(row.id)
        if not row.artifact_digest or (row.id in prepared and not mapping_matches_admission(row, facts)):
            continue
        result.append(
            BackendArtifact(
                artifact_id=row.artifact_id,
                version=row.artifact_version,
                digest=row.artifact_digest,
                media_type=row.media_type,
                integrity_ref=row.integrity_ref,
                provenance_ref=row.provenance_ref,
                image_ref=row.image_ref,
                machine_type=row.machine_type,
                disk_size_gb=row.disk_size_gb,
                disk_type=row.disk_type,
                materialization=facts,
                image_id=facts.image_id if facts is not None else "",
            )
        )
    return result


def disable_raes_image_mapping(
    *,
    provider: str,
    source_name: str,
    source_version: str = "",
) -> RaesImageMappingView:
    """Soft-disable an existing mapping (``enabled=False``) by natural key.

    Preserves the row and its ``image_ref`` for audit; realization then fails
    loud. Raises :class:`RaesImageMappingError` when no such mapping exists --
    the surface disables what is registered rather than creating a disabled
    placeholder (disable is not delete, and not upsert).
    """
    from engine.models import RaesImageMapping

    normalized_provider = _normalize_provider(provider)
    name = _require(source_name, field="source_name")
    version = (source_version or "").strip()
    try:
        mapping = RaesImageMapping.objects.get(
            provider=normalized_provider,
            source_name=name,
            source_version=version,
        )
    except RaesImageMapping.DoesNotExist as exc:
        raise RaesImageMappingError(f"no mapping for {normalized_provider}:{name}@{version or '*'}") from exc
    if mapping.enabled:
        mapping.enabled = False
        mapping.save(update_fields=["enabled", "updated_at"])
    return _to_view(mapping)


def _to_view(mapping: RaesImageMapping) -> RaesImageMappingView:
    """Project a model row onto the allowlisted read DTO."""
    return RaesImageMappingView(
        id=mapping.pk,
        provider=mapping.provider,
        source_name=mapping.source_name,
        source_version=mapping.source_version,
        image_ref=mapping.image_ref,
        machine_type=mapping.machine_type,
        disk_size_gb=mapping.disk_size_gb,
        disk_type=mapping.disk_type,
        enabled=mapping.enabled,
        notes=mapping.notes,
        artifact_id=mapping.artifact_id,
        artifact_version=mapping.artifact_version,
        artifact_digest=mapping.artifact_digest,
        media_type=mapping.media_type,
        integrity_ref=mapping.integrity_ref,
        provenance_ref=mapping.provenance_ref,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


_SHA256_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


def _stripped(value: str | None) -> str:
    """Return ``value`` stripped, or ``""`` when it is None/blank."""
    return (value or "").strip()


def _validate_portable_identity(opts: RaesImageMappingOptions) -> dict[str, str]:
    """Return the normalized portable-identity fields, or raise on a half-populated set.

    Either all five portable fields are blank (a legacy alias-only mapping) or all
    are present (a portable mapping); a partial set is rejected here with a clear
    error before the database CheckConstraint would reject it, and the digest must
    be a canonical ``sha256:`` value so a disclosure built from it is well-formed.
    """
    fields = {
        "artifact_id": _stripped(opts.artifact_id),
        "artifact_version": _stripped(opts.artifact_version),
        "artifact_digest": _stripped(opts.artifact_digest),
        "media_type": _stripped(opts.media_type),
        "integrity_ref": _stripped(opts.integrity_ref),
        "provenance_ref": _stripped(opts.provenance_ref),
    }
    present = [key for key, value in fields.items() if value]
    if not present:
        return fields
    if len(present) != len(fields):
        missing = sorted(set(fields) - set(present))
        raise RaesImageMappingError(
            f"a portable artifact mapping requires all of artifact_id, artifact_version, artifact_digest, "
            f"media_type, integrity_ref, provenance_ref; missing: {', '.join(missing)}"
        )
    if not _SHA256_DIGEST.fullmatch(fields["artifact_digest"]):
        raise RaesImageMappingError("artifact_digest must be a canonical 'sha256:<64 hex>' value")
    return fields


def _normalize_provider(provider: str) -> str:
    """Return the lower-cased provider if it is a known choice, else raise."""
    from engine.models import RaesImageMapping

    value = (provider or "").strip().lower()
    valid = {choice for choice, _label in RaesImageMapping.Provider.choices}
    if value not in valid:
        raise RaesImageMappingError(f"provider must be one of {sorted(valid)}")
    return value


def _require(value: str, *, field: str) -> str:
    """Return a stripped non-empty string or raise RaesImageMappingError naming ``field``."""
    if not isinstance(value, str) or not value.strip():
        raise RaesImageMappingError(f"{field} must be a non-empty string")
    return value.strip()
