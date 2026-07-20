"""Tenant-managed ACES image registry service (ADR-032-R2).

The single validated write path for :class:`engine.models.AcesImageMapping` -- the
tenant operator surface (and any future management API) goes through this, so
validation and idempotent upsert-by-natural-key live in one place. The provisioner
reads and resolves these rows at realization; it does not use this seam (CQRS: the
platform writes, the provisioner reads).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from engine.models import AcesImageMapping

__all__ = [
    "AcesImageMappingError",
    "AcesImageMappingOptions",
    "AcesImageMappingView",
    "disable_aces_image_mapping",
    "list_aces_image_mappings",
    "upsert_aces_image_mapping",
]


class AcesImageMappingError(ValueError):
    """Raised when an ACES image mapping fails validation."""


@dataclass(frozen=True)
class AcesImageMappingOptions:
    """Optional fields for an ACES image mapping (beyond the natural key + image ref)."""

    source_version: str = ""
    machine_type: str = ""
    disk_size_gb: int | None = None
    disk_type: str = ""
    enabled: bool = True
    notes: str = ""


@dataclass(frozen=True)
class AcesImageMappingView:
    """Allowlisted read projection of an :class:`engine.models.AcesImageMapping` row.

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
    created_at: datetime
    updated_at: datetime


def upsert_aces_image_mapping(
    *,
    provider: str,
    source_name: str,
    image_ref: str,
    options: AcesImageMappingOptions | None = None,
) -> AcesImageMapping:
    """Create or update an ACES image mapping, keyed on (provider, source_name, source_version).

    Idempotent so tenant automation can converge the registry declaratively. A
    blank ``source_version`` registers the any-version fallback. Retire a mapping
    by upserting with ``options.enabled=False`` (preserves audit; realization then
    fails loud) rather than deleting it.
    """
    from engine.models import AcesImageMapping

    opts = options or AcesImageMappingOptions()
    normalized_provider = _normalize_provider(provider)
    name = _require(source_name, field="source_name")
    ref = _require(image_ref, field="image_ref")
    if opts.disk_size_gb is not None and opts.disk_size_gb <= 0:
        raise AcesImageMappingError("disk_size_gb must be a positive integer when set")

    mapping, _created = AcesImageMapping.objects.update_or_create(
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
        },
    )
    return mapping


def list_aces_image_mappings(
    *,
    provider: str | None = None,
    include_disabled: bool = True,
) -> list[AcesImageMappingView]:
    """Return registry rows as allowlisted DTOs in stable natural-key order.

    Optional ``provider`` filters to one provider (normalized/validated exactly
    like the write path, so an unknown provider raises rather than silently
    returning nothing). ``include_disabled=False`` hides soft-disabled rows the
    way the provisioner resolver ignores them; the default shows them so an
    operator can audit and re-enable.
    """
    from engine.models import AcesImageMapping

    queryset = AcesImageMapping.objects.all().order_by("provider", "source_name", "source_version")
    if provider is not None:
        queryset = queryset.filter(provider=_normalize_provider(provider))
    if not include_disabled:
        queryset = queryset.filter(enabled=True)
    return [_to_view(row) for row in queryset]


def disable_aces_image_mapping(
    *,
    provider: str,
    source_name: str,
    source_version: str = "",
) -> AcesImageMappingView:
    """Soft-disable an existing mapping (``enabled=False``) by natural key.

    Preserves the row and its ``image_ref`` for audit; realization then fails
    loud. Raises :class:`AcesImageMappingError` when no such mapping exists --
    the surface disables what is registered rather than creating a disabled
    placeholder (disable is not delete, and not upsert).
    """
    from engine.models import AcesImageMapping

    normalized_provider = _normalize_provider(provider)
    name = _require(source_name, field="source_name")
    version = (source_version or "").strip()
    try:
        mapping = AcesImageMapping.objects.get(
            provider=normalized_provider,
            source_name=name,
            source_version=version,
        )
    except AcesImageMapping.DoesNotExist as exc:
        raise AcesImageMappingError(f"no mapping for {normalized_provider}:{name}@{version or '*'}") from exc
    if mapping.enabled:
        mapping.enabled = False
        mapping.save(update_fields=["enabled", "updated_at"])
    return _to_view(mapping)


def _to_view(mapping: AcesImageMapping) -> AcesImageMappingView:
    """Project a model row onto the allowlisted read DTO."""
    return AcesImageMappingView(
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
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


def _normalize_provider(provider: str) -> str:
    """Return the lower-cased provider if it is a known choice, else raise."""
    from engine.models import AcesImageMapping

    value = (provider or "").strip().lower()
    valid = {choice for choice, _label in AcesImageMapping.Provider.choices}
    if value not in valid:
        raise AcesImageMappingError(f"provider must be one of {sorted(valid)}")
    return value


def _require(value: str, *, field: str) -> str:
    """Return a stripped non-empty string or raise AcesImageMappingError naming ``field``."""
    if not isinstance(value, str) or not value.strip():
        raise AcesImageMappingError(f"{field} must be a non-empty string")
    return value.strip()
