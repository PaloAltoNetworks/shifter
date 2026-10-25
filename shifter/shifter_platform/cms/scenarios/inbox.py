"""In-box scenario bootstrap seed (#1578, ADR-034).

The packs registered into the tenant by default are *not* loaded through a
privileged code path. They are declared in a manifest and registered through the
SAME :func:`cms.services.register_pack` service an operator uses. This is the
dogfooding requirement of ADR-053/ADR-034: the in-box seed and operator
content share one ingestion path.

The shipped manifest (:data:`SHIPPED_INBOX_MANIFEST`) declares the in-box
seed. The mechanism is exercised by tests; entries are added as
first-party packs are authored.

Bootstrap asks the service for an idempotent retry: an exact immutable identity
is a no-op, while manifest or byte drift is a visible conflict.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug
from django.db import transaction

from cms.exceptions import CMSError
from cms.models import RaesPackageSource
from cms.services import PackRegistrationRequest, RegisteredPack, register_pack
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.raes.pack_conformance import validate_pack_contract
from shared.raes.package_loader import resolve_pack_scenario_path
from shared.schemas.raes_package_source import (
    PackageSourceRecord,
    RaesPackageSourceError,
    validate_package_source,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

# The declared in-box pack manifest that ships with Shifter.
SHIPPED_INBOX_MANIFEST = Path(__file__).parent / "inbox_packs" / "manifest.yaml"

_ENTRY_FIELDS = frozenset(
    {
        "scenario_id",
        "source_kind",
        "contract_kind",
        "contract_profile",
        "package_ref",
        "package_version",
        "package_digest",
        "expected_package_digest",
        "lock_ref",
        "lock_digest",
        "provenance",
    }
)
_TEXT_FIELD_LIMITS = {
    "scenario_id": 100,
    "source_kind": 16,
    "contract_kind": 32,
    "contract_profile": 128,
    "package_ref": 512,
    "package_version": 128,
    "package_digest": 71,
    "expected_package_digest": 71,
    "lock_ref": 512,
    "lock_digest": 71,
}


class InboxManifestError(CMSError):
    """Raised when the in-box seed declaration is absent or malformed."""


def load_inbox_manifest(manifest_path: Path | None = None) -> list[PackRegistrationRequest]:
    """Parse and validate the complete in-box declaration, or fail closed."""
    path = Path(manifest_path) if manifest_path is not None else SHIPPED_INBOX_MANIFEST
    if not path.is_file():
        raise InboxManifestError("in-box pack manifest is missing")
    try:
        with path.open(encoding="utf-8") as handle:
            doc = yaml.safe_load(handle)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise InboxManifestError("in-box pack manifest is unreadable or invalid YAML") from exc
    if not isinstance(doc, dict) or set(doc) != {"packs"}:
        raise InboxManifestError("in-box pack manifest must contain exactly one 'packs' declaration")
    packs = doc["packs"]
    if not isinstance(packs, list):
        raise InboxManifestError("in-box pack manifest 'packs' declaration must be a list")

    requests: list[PackRegistrationRequest] = []
    for index, entry in enumerate(packs):
        if not isinstance(entry, dict):
            raise InboxManifestError(f"in-box pack manifest entry {index} must be a mapping")
        requests.append(_entry_to_request(entry, index=index))
    return requests


def register_inbox_packs(
    *, actor: User, manifest_path: Path | None = None, request_id: str = ""
) -> list[RegisteredPack]:
    """Register every declared in-box pack through the uniform ingestion service.

    Args:
        actor: The registering user (must pass the CMS authoring gate).
        manifest_path: Optional manifest override (defaults to the shipped one).
        request_id: Optional audit correlation id.

    Returns:
        The packs newly registered by this call (already-registered ids skipped).
    """
    selected_manifest = Path(manifest_path) if manifest_path is not None else SHIPPED_INBOX_MANIFEST
    requests = load_inbox_manifest(selected_manifest)
    trusted_release = selected_manifest.resolve() == SHIPPED_INBOX_MANIFEST.resolve()
    registered: list[RegisteredPack] = []
    # The declaration is one deploy input. A failure in any entry rolls back
    # earlier registrations and their strict audit rows instead of installing a
    # silently partial in-box registration.
    with transaction.atomic():
        for request in requests:
            result = register_pack(
                user=actor,
                request=request,
                request_id=request_id,
                idempotent=True,
            )
            if result.created:
                registered.append(result)
            if trusted_release:
                _promote_release_conformance(request=request, actor=actor, request_id=request_id)
    return registered


def _promote_release_conformance(*, request: PackRegistrationRequest, actor: User, request_id: str) -> None:
    """Compile and promote one immutable, checked-in release-manifest pack.

    This release-manifest entrypoint is used only by shipped-pack bootstrap;
    operators use the shared registered-pack conformance service. Registration has already run the
    upstream environment-pack validator and bound the canonical digest; this
    gate additionally exercises the real RAES load, plan, Shifter target, and
    apply-contract path before storing the release-owned conformance fact.
    """
    if request.source_kind != "repo":
        raise InboxManifestError("shipped in-box packs must be repository-backed")
    pack_root = (Path(settings.RAES_PACKAGE_ROOT).resolve() / request.package_ref).resolve()
    scenario_path = resolve_pack_scenario_path(pack_root)
    try:
        validate_pack_contract(scenario_path, request_id or "inbox-release-conformance")
    except Exception as exc:
        raise InboxManifestError("shipped in-box pack failed release conformance") from exc

    source = RaesPackageSource.objects.get(scenario_id=request.scenario_id)
    source.conformance_status = RaesPackageSource.ConformanceStatus.PASSED
    source.conformance_report_ref = f"release://{request.package_ref}@{request.package_version}"
    source.save(update_fields=["conformance_status", "conformance_report_ref", "updated_at"])
    audit_log(
        AuditEvent(
            entity_type=AuditEntityType.SCENARIO,
            entity_id=0,
            entity_ref=source.scenario_id,
            action=AuditAction.UPDATE,
            actor_type=AuditActorType.USER,
            actor_id=actor.id,
            new_state={
                "scenario_id": source.scenario_id,
                "package_digest": source.package_digest,
                "conformance_status": source.conformance_status,
                "conformance_report_ref": source.conformance_report_ref,
            },
            request_id=request_id,
        ),
        strict=True,
    )


def _entry_to_request(entry: dict[str, Any], *, index: int) -> PackRegistrationRequest:
    """Build one request after strict declaration and shared-contract validation."""
    if not set(entry).issubset(_ENTRY_FIELDS):
        raise InboxManifestError(f"in-box pack manifest entry {index} has unsupported fields")
    request = PackRegistrationRequest(
        scenario_id=entry.get("scenario_id", ""),
        source_kind=entry.get("source_kind", "repo"),
        contract_kind=entry.get("contract_kind", "raes"),
        contract_profile=entry.get("contract_profile", "shifter"),
        package_ref=entry.get("package_ref", ""),
        package_version=entry.get("package_version", ""),
        package_digest=entry.get("package_digest", ""),
        expected_package_digest=entry.get("expected_package_digest", ""),
        lock_ref=entry.get("lock_ref", ""),
        lock_digest=entry.get("lock_digest", ""),
        provenance=entry.get("provenance", {}),
    )
    for field, limit in _TEXT_FIELD_LIMITS.items():
        value = getattr(request, field)
        if not isinstance(value, str) or len(value) > limit:
            raise InboxManifestError(f"in-box pack manifest entry {index} has an invalid {field}")
    try:
        validate_slug(request.scenario_id)
    except ValidationError as exc:
        raise InboxManifestError(f"in-box pack manifest entry {index} has an invalid scenario_id") from exc
    if not isinstance(request.provenance, dict):
        raise InboxManifestError(f"in-box pack manifest entry {index} has invalid provenance")
    try:
        validate_package_source(
            PackageSourceRecord(
                source_kind=request.source_kind,
                contract_kind=request.contract_kind,
                contract_profile=request.contract_profile,
                package_ref=request.package_ref,
                package_version=request.package_version,
                package_digest=request.package_digest,
                conformance_status="pending",
                lock_ref=request.lock_ref,
                lock_digest=request.lock_digest,
                provenance=request.provenance,
            )
        )
    except RaesPackageSourceError as exc:
        raise InboxManifestError(f"in-box pack manifest entry {index} violates the package-source contract") from exc
    return request
