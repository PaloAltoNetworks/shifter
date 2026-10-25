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
from shared.raes.image_policy import validate_management_ssh_port, validate_management_ssh_username

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
    """Validation failure with an explicit user-facing message, separate from diagnostics."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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
    management_ssh_port: int = 22
    management_ssh_username: str = ""
    image_kind: str = "image"
    bootstrap_capability: str = "standard"
    participant_container_name: str = ""
    participant_username: str = ""
    participant_readiness_contract: str = ""
    participant_readiness_manifest_sha256: str = ""
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
    management_ssh_port: int
    management_ssh_username: str
    image_kind: str
    bootstrap_capability: str
    participant_container_name: str
    participant_username: str
    participant_readiness_contract: str
    participant_readiness_manifest_sha256: str
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
    try:
        management_port = validate_management_ssh_port(opts.management_ssh_port)
        management_user = validate_management_ssh_username(opts.management_ssh_username)
    except ValueError as exc:
        raise RaesImageMappingError(str(exc)) from None
    portable = _validate_portable_identity(opts)
    runtime_profile = _validate_runtime_profile(normalized_provider, ref, opts, management_user)
    if runtime_profile["image_kind"] == "machine-image" and portable["artifact_digest"]:
        raise RaesImageMappingError("machine-image mappings do not support portable artifact admission")

    mapping, _created = RaesImageMapping.objects.update_or_create(
        provider=normalized_provider,
        source_name=name,
        source_version=(opts.source_version or "").strip(),
        defaults={
            "image_ref": ref,
            "machine_type": (opts.machine_type or "").strip(),
            "disk_size_gb": opts.disk_size_gb,
            "management_ssh_port": management_port,
            "management_ssh_username": management_user,
            **runtime_profile,
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
                management_ssh_port=row.management_ssh_port,
                management_ssh_username=row.management_ssh_username,
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
        management_ssh_port=mapping.management_ssh_port,
        management_ssh_username=mapping.management_ssh_username,
        image_kind=mapping.image_kind,
        bootstrap_capability=mapping.bootstrap_capability,
        participant_container_name=mapping.participant_container_name,
        participant_username=mapping.participant_username,
        participant_readiness_contract=mapping.participant_readiness_contract,
        participant_readiness_manifest_sha256=mapping.participant_readiness_manifest_sha256,
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
_MACHINE_IMAGE_REF = re.compile(
    r"^projects/[a-z0-9][-a-z0-9.:]*/global/machineImages/[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$"
)
_EXACT_GCE_IMAGE_REF = re.compile(r"^projects/[a-z0-9][-a-z0-9.:]*/global/images/[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_READINESS_CONTRACT = "participant-readiness/v1"
_PRECONFIGURED_MACHINE_HOST = "preconfigured-machine-host"


def _validate_runtime_profile(
    provider: str,
    image_ref: str,
    opts: RaesImageMappingOptions,
    management_user: str,
) -> dict[str, str]:
    """Validate the optional provider realization profile stored with a mapping."""
    image_kind, bootstrap = _validated_profile_discriminator(opts)
    container = (opts.participant_container_name or "").strip()
    participant_user = (opts.participant_username or "").strip()
    readiness_contract = (opts.participant_readiness_contract or "").strip()
    readiness_sha = (opts.participant_readiness_manifest_sha256 or "").strip()
    participant_fields = (container, participant_user, readiness_contract, readiness_sha)
    if image_kind == "image" and bootstrap != _PRECONFIGURED_MACHINE_HOST:
        _validate_boot_image_fields(participant_fields)
    else:
        _validate_preconfigured_host_fields(
            provider, image_ref, image_kind, bootstrap, management_user, participant_fields
        )
    return {
        "image_kind": image_kind,
        "bootstrap_capability": bootstrap,
        "participant_container_name": container,
        "participant_username": participant_user,
        "participant_readiness_contract": readiness_contract,
        "participant_readiness_manifest_sha256": readiness_sha,
    }


def _validated_profile_discriminator(opts: RaesImageMappingOptions) -> tuple[str, str]:
    """Validate the image kind and bootstrap capability before profile details."""
    image_kind = (opts.image_kind or "image").strip()
    bootstrap = (opts.bootstrap_capability or "standard").strip()
    if image_kind not in {"image", "machine-image"}:
        raise RaesImageMappingError("image_kind must be 'image' or 'machine-image'")
    if not re.fullmatch(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", bootstrap):
        raise RaesImageMappingError("bootstrap_capability must be a lowercase logical capability")
    return image_kind, bootstrap


def _validate_boot_image_fields(participant_fields: tuple[str, str, str, str]) -> None:
    """Reject participant-host metadata on a normal boot image."""
    if any(participant_fields):
        raise RaesImageMappingError("participant host fields require bootstrap_capability 'preconfigured-machine-host'")


def _validate_preconfigured_host_fields(
    provider: str,
    image_ref: str,
    image_kind: str,
    bootstrap: str,
    management_user: str,
    participant_fields: tuple[str, str, str, str],
) -> None:
    """Require the provider and complete participant-host readiness contract."""
    container, participant_user, readiness_contract, readiness_sha = participant_fields
    if provider != "gce":
        raise RaesImageMappingError("preconfigured host mappings currently require provider 'gce'")
    _validate_preconfigured_image_ref(image_ref, image_kind)
    if bootstrap != _PRECONFIGURED_MACHINE_HOST:
        raise RaesImageMappingError("machine-image mappings require bootstrap_capability 'preconfigured-machine-host'")
    if not management_user:
        raise RaesImageMappingError("preconfigured host mappings require management_ssh_username")
    if not all(participant_fields):
        raise RaesImageMappingError(
            "preconfigured hosts require participant container, username, readiness contract, and manifest digest"
        )
    if not _CONTAINER_NAME.fullmatch(container):
        raise RaesImageMappingError("participant_container_name is invalid")
    try:
        validate_management_ssh_username(participant_user)
    except ValueError:
        raise RaesImageMappingError("participant_username must be a local OS username") from None
    if readiness_contract != _READINESS_CONTRACT:
        raise RaesImageMappingError(f"participant_readiness_contract must be '{_READINESS_CONTRACT}'")
    if not re.fullmatch(r"[0-9a-f]{64}", readiness_sha):
        raise RaesImageMappingError("participant_readiness_manifest_sha256 must be a lowercase SHA-256 digest")


def _validate_preconfigured_image_ref(image_ref: str, image_kind: str) -> None:
    """Require an exact source for either supported preconfigured host image kind."""
    if image_kind == "machine-image" and not _MACHINE_IMAGE_REF.fullmatch(image_ref):
        raise RaesImageMappingError(
            "machine-image image_ref must be an exact 'projects/<project>/global/machineImages/<name>' resource"
        )
    if image_kind == "image" and not _EXACT_GCE_IMAGE_REF.fullmatch(image_ref):
        raise RaesImageMappingError(
            "preconfigured host image_ref must be an exact 'projects/<project>/global/images/<name>' resource"
        )


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
