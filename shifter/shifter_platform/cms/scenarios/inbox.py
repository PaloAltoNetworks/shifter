"""In-box scenario-catalog bootstrap (#1578, ADR-034).

The packs Shifter ships by default are *not* loaded through a privileged code
path. They are declared in a manifest and registered through the SAME
:func:`cms.services.register_pack` service an operator uses. This is the
dogfooding requirement of ADR-033/ADR-034: the shipped catalog and operator
content share one ingestion path.

There are no conformant default scenario packs yet (program #1584), so the
shipped manifest (:data:`SHIPPED_INBOX_MANIFEST`) declares an empty pack list.
The mechanism is in place and exercised by tests; entries are added as first-party
packs are authored.

Bootstrap asks the service for an idempotent retry: an exact immutable identity
is a no-op, while manifest or byte drift is a visible conflict.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from django.core.exceptions import ValidationError
from django.core.validators import validate_slug
from django.db import transaction

from cms.exceptions import CMSError
from cms.services import PackRegistrationRequest, RegisteredPack, register_pack
from shared.schemas.aces_package_source import (
    AcesPackageSourceError,
    PackageSourceRecord,
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
    "lock_ref": 512,
    "lock_digest": 71,
}


class InboxManifestError(CMSError):
    """Raised when the shipped catalog declaration is absent or malformed."""


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
    requests = load_inbox_manifest(manifest_path)
    registered: list[RegisteredPack] = []
    # The declaration is one deploy input. A failure in any entry rolls back
    # earlier registrations and their strict audit rows instead of installing a
    # silently partial in-box catalog.
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
    return registered


def _entry_to_request(entry: dict[str, Any], *, index: int) -> PackRegistrationRequest:
    """Build one request after strict declaration and shared-contract validation."""
    if not set(entry).issubset(_ENTRY_FIELDS):
        raise InboxManifestError(f"in-box pack manifest entry {index} has unsupported fields")
    request = PackRegistrationRequest(
        scenario_id=entry.get("scenario_id", ""),
        source_kind=entry.get("source_kind", "repo"),
        contract_kind=entry.get("contract_kind", "aces"),
        contract_profile=entry.get("contract_profile", "shifter"),
        package_ref=entry.get("package_ref", ""),
        package_version=entry.get("package_version", ""),
        package_digest=entry.get("package_digest", ""),
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
    except AcesPackageSourceError as exc:
        raise InboxManifestError(f"in-box pack manifest entry {index} violates the package-source contract") from exc
    return request
