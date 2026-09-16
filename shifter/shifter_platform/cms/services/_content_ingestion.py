"""Uniform, entitlement-blind content ingestion (#1578, ADR-034).

One CMS service boundary registers a pack, identically for shipped, public,
private, and self-authored packs. There is no "built-in" / "imported" /
"authored" fork: ``source_kind`` is a *resolver* fact, not a provenance one, and
nothing here branches on how the operator obtained the pack.

The boundary:

- **authorizes who may register** content via the canonical CMS authoring gate,
  and never adds an entitlement / acquisition / source-identity check after it
  (entitlement is resolved out-of-band, per ADR-034);
- **validates the incoming pack as foreign input** (``cms.scenarios.pack_validation``)
  so broken / malformed / non-conformant content is rejected fail-closed;
- **fails closed on duplicate RAES identities**;
- **keeps registration separate from conformance**: object-backed packs become
  launchable only after their immutable source passes the shared conformance
  gate through the containment-checked object resolver;
- **persists a provenance-only reference** (:class:`cms.models.RaesPackageSource`,
  whose ``save`` enforces the reference-only contract) and **audits** the result
  with sanitized fields only.

Every caller — the in-box bootstrap, the operator management command, and the
DRF authoring endpoint — uses :func:`register_pack`; there is no privileged code
path for the in-box seed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError, transaction

from cms.exceptions import CMSError
from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import (
    PackDigestError,
    PackValidationError,
    validate_pack,
    verify_pack_digest,
)
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.auth import validate_cms_authoring_user
from shared.log_sanitize import safe_log_value
from shared.schemas.raes_package_source import RaesPackageSourceError

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

_OBJECT_SOURCE_KIND = "object"

# Registration is not conformance. Conformance ("passed") is a trust fact
# established by a separate, trusted conformance process (the RAES conformance
# gate), never asserted by the registering caller — otherwise an API/CLI caller
# could promote its own claim into the registry's authoritative launchability
# decision. Every registration therefore lands non-passed, and conformance is
# promoted out of band. ``conformance_status`` / ``conformance_report_ref`` are
# deliberately NOT part of the registration request.
_REGISTRATION_CONFORMANCE_STATUS = "pending"


@dataclass(frozen=True)
class PackRegistrationRequest:
    """Source-agnostic, entitlement-blind input to :func:`register_pack`.

    The shape does not vary with provenance: an in-box, public, private, or
    self-authored pack is described by the same fields. ``provenance`` is bounded
    reference metadata only (validated by the model), never a body or credential.

    Conformance status is intentionally absent: a caller cannot assert that a
    pack has passed conformance (see :data:`_REGISTRATION_CONFORMANCE_STATUS`).
    """

    scenario_id: str
    source_kind: str
    contract_kind: str
    contract_profile: str
    package_ref: str
    package_version: str
    package_digest: str
    lock_ref: str = ""
    lock_digest: str = ""
    provenance: dict[str, object] | None = None
    # Explicit optimistic concurrency precondition for an intentional revision.
    # This is registration control, never part of the portable pack identity.
    expected_package_digest: str = ""


@dataclass(frozen=True)
class RegisteredPack:
    """Bounded result of a successful registration (no reference payload)."""

    scenario_id: str
    source_kind: str
    contract_kind: str
    contract_profile: str
    conformance_status: str
    created: bool


def register_pack(
    *,
    user: User,
    request: PackRegistrationRequest,
    request_id: str = "",
    idempotent: bool = False,
) -> RegisteredPack:
    """Register a pack through the single uniform ingestion boundary.

    Args:
        user: The actor. Must pass the CMS authoring authorization gate. This is
            the WHO-may-register check, not an entitlement-to-acquire check.
        request: The source-agnostic registration input.
        request_id: Optional correlation id for the audit record.
        idempotent: Return ``created=False`` when the same immutable request is
            already registered. Any drift remains a conflict. Used by deploy
            bootstrap retries; ordinary API/CLI duplicates still fail.

    Returns:
        A bounded :class:`RegisteredPack` summary.

    Raises:
        TypeError / django PermissionDenied: from the authorization gate.
        CMSError: on a duplicate id, an invalid pack, a
            scenario_id that does not match the pack's validated identity, or an
            invalid reference record.
    """
    validate_cms_authoring_user(user, "register_pack")
    if request.expected_package_digest and not re.fullmatch(r"sha256:[a-f0-9]{64}", request.expected_package_digest):
        raise CMSError("Invalid expected package digest")
    existing = RaesPackageSource.objects.filter(scenario_id=request.scenario_id).first()
    if existing is not None:
        return _existing_registration(existing, user, request, request_id=request_id, idempotent=idempotent)
    _bind_scenario_id_to_pack_identity(request)

    try:
        with transaction.atomic():
            row = RaesPackageSource.objects.create(
                scenario_id=request.scenario_id,
                source_kind=request.source_kind,
                contract_kind=request.contract_kind,
                contract_profile=request.contract_profile,
                package_ref=request.package_ref,
                package_version=request.package_version,
                # The registration boundary verified this canonical digest
                # against the exact local pack inventory and payload bytes.
                # Launch re-verifies it immediately before loading SDL.
                package_digest=request.package_digest,
                lock_ref=request.lock_ref,
                lock_digest=request.lock_digest,
                # Conformance is never caller-asserted at registration; a trusted
                # conformance process promotes it out of band.
                conformance_status=_REGISTRATION_CONFORMANCE_STATUS,
                conformance_report_ref="",
                provenance=dict(request.provenance or {}),
                registered_by=user,
            )
            _audit_registration(row, user, request_id)
    except RaesPackageSourceError as exc:
        # Reference-shape violation from the model's provenance-only validator.
        raise CMSError("Invalid pack reference") from exc
    except IntegrityError as exc:
        if idempotent:
            raced = RaesPackageSource.objects.filter(scenario_id=request.scenario_id).first()
            if raced is not None:
                return _reuse_existing(raced, request, idempotent=True)
        raise CMSError(f"A pack with id '{request.scenario_id}' is already registered") from exc

    logger.info(
        "register_pack: registered scenario_id=%s source_kind=%s",
        safe_log_value(row.scenario_id),
        row.source_kind,
    )
    return RegisteredPack(
        scenario_id=row.scenario_id,
        source_kind=row.source_kind,
        contract_kind=row.contract_kind,
        contract_profile=row.contract_profile,
        conformance_status=row.conformance_status,
        created=True,
    )


def _existing_registration(
    existing: RaesPackageSource,
    user: User,
    request: PackRegistrationRequest,
    *,
    request_id: str,
    idempotent: bool,
) -> RegisteredPack:
    """Handle existing registration."""
    if request.expected_package_digest:
        return _replace_existing(user, request, request_id=request_id, idempotent=idempotent)
    return _reuse_existing(existing, request, idempotent=idempotent)


_IDENTITY_FIELDS = (
    "source_kind",
    "contract_kind",
    "contract_profile",
    "package_ref",
    "package_version",
    "package_digest",
    "lock_ref",
    "lock_digest",
    "provenance",
)


def _identity(value: RaesPackageSource | PackRegistrationRequest) -> dict[str, object]:
    """Capture bounded reference identity, including the optional provenance map."""
    return {
        name: (getattr(value, name) or {} if name == "provenance" else getattr(value, name))
        for name in _IDENTITY_FIELDS
    }


def _replace_existing(
    user: User,
    request: PackRegistrationRequest,
    *,
    request_id: str,
    idempotent: bool,
) -> RegisteredPack:
    """Admit an explicit new version while preserving prior reference evidence.

    In-flight range inputs are immutable snapshots owned by the engine; this
    service changes only the catalog's current source. Conformance must be
    established again for the new digest through the existing trusted process.
    """
    _bind_scenario_id_to_pack_identity(request)
    with transaction.atomic():
        row = RaesPackageSource.objects.select_for_update().get(scenario_id=request.scenario_id)
        if _identity(row) == _identity(request):
            return _reuse_existing(row, request, idempotent=idempotent)
        if row.package_digest != request.expected_package_digest or row.package_version == request.package_version:
            raise CMSError("Pack revision conflicts with the current immutable identity")
        previous = _identity(row)
        for name, value in _identity(request).items():
            setattr(row, name, value)
        row.conformance_status = _REGISTRATION_CONFORMANCE_STATUS
        row.conformance_report_ref = ""
        row.registered_by = user
        try:
            row.save()
        except RaesPackageSourceError as exc:
            raise CMSError("Invalid pack reference") from exc
        try:
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.SCENARIO,
                    entity_id=0,
                    action=AuditAction.UPDATE,
                    actor_type=AuditActorType.USER,
                    actor_id=user.id,
                    request_id=request_id,
                    previous_state={"scenario_id": row.scenario_id, **previous},
                    new_state={"scenario_id": row.scenario_id, **_identity(row), "conformance_status": "pending"},
                ),
                strict=True,
            )
        except Exception as exc:
            raise CMSError("pack revision audit failed") from exc
        return RegisteredPack(
            row.scenario_id,
            row.source_kind,
            row.contract_kind,
            row.contract_profile,
            row.conformance_status,
            created=False,
        )


def _reuse_existing(
    row: RaesPackageSource,
    request: PackRegistrationRequest,
    *,
    idempotent: bool,
) -> RegisteredPack:
    """Return an exact idempotent retry or reject duplicate/drifted identity."""
    if not idempotent:
        raise CMSError(f"A pack with id '{request.scenario_id}' is already registered")
    if _identity(row) != _identity(request):
        raise CMSError(f"A pack with id '{request.scenario_id}' is already registered with different identity")
    # A no-op retry still validates the referenced bytes. Otherwise a mutable
    # repo pack could drift while bootstrap silently reported success.
    _bind_scenario_id_to_pack_identity(request)
    return RegisteredPack(
        scenario_id=row.scenario_id,
        source_kind=row.source_kind,
        contract_kind=row.contract_kind,
        contract_profile=row.contract_profile,
        conformance_status=row.conformance_status,
        created=False,
    )


def _bind_scenario_id_to_pack_identity(request: PackRegistrationRequest) -> None:
    """Validate a resolvable (repo) pack and bind the catalog id to its identity.

    For repo packs the pack is validated as foreign input, the caller's
    ``scenario_id`` MUST equal the pack's validated identity, and the advertised
    digest MUST match the canonical RAES associated-artifact identity. Staging
    is required to remain immutable; launch repeats the byte binding immediately
    before SDL load so a later replacement fails closed.

    Object-backed packs are resolved and identity-bound by the shared conformance
    service before promotion. The launch resolver repeats the same source and
    byte binding before use; registration itself performs no object download.
    """
    if request.source_kind == _OBJECT_SOURCE_KIND:
        return
    pack_root = _resolve_repo_pack_root(request.package_ref)
    try:
        validated_name = validate_pack(pack_root)
    except PackValidationError as exc:
        logger.warning(
            "register_pack: pack failed validation scenario_id=%s reasons=%s",
            safe_log_value(request.scenario_id),
            safe_log_value(str(exc)),
        )
        raise CMSError("pack failed ingestion validation") from exc
    if validated_name != request.scenario_id:
        raise CMSError("scenario_id does not match the pack's validated identity")
    try:
        digest_matches = verify_pack_digest(pack_root, request.package_digest)
    except PackDigestError as exc:
        logger.warning(
            "register_pack: pack digest could not be verified scenario_id=%s",
            safe_log_value(request.scenario_id),
        )
        raise CMSError("pack content digest could not be verified") from exc
    if not digest_matches:
        raise CMSError("package_digest does not match the validated pack content")


def _resolve_repo_pack_root(package_ref: str) -> Path:
    """Resolve a repo-relative package_ref to a contained pack root directory."""
    root = Path(settings.RAES_PACKAGE_ROOT).resolve()
    candidate = (root / package_ref).resolve()
    if candidate != root and root not in candidate.parents:
        raise CMSError("package_ref escapes the configured package root")
    return candidate


def _audit_registration(row: RaesPackageSource, user: User, request_id: str) -> None:
    """Record the sanitized registration audit as a fail-closed safety control."""
    try:
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.SCENARIO,
                # RaesPackageSource PKs are UUIDs; existing scenario audit records
                # use 0 and carry the scenario_id in the state payload.
                entity_id=0,
                action=AuditAction.CREATE,
                actor_type=AuditActorType.USER,
                actor_id=getattr(user, "id", None),
                new_state={
                    "scenario_id": row.scenario_id,
                    "source_kind": row.source_kind,
                    "contract_kind": row.contract_kind,
                    "contract_profile": row.contract_profile,
                    "package_digest": row.package_digest,
                    "conformance_status": row.conformance_status,
                    "result": "registered",
                },
                request_id=request_id,
            ),
            strict=True,
        )
    except Exception as exc:
        raise CMSError("pack registration audit failed") from exc
