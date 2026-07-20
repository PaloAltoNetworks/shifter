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
- **fails closed on shadowing and duplicates**, preserving the registry's
  no-shadow posture (ADR-024) so a pack cannot mask an active legacy scenario;
- **keeps object-backed packs non-launchable** until #1567 supplies a
  containment-checked object resolver (an object row may not be registered
  conformance-``passed``, which is what would make it launchable);
- **persists a provenance-only reference** (:class:`cms.models.AcesPackageSource`,
  whose ``save`` enforces the reference-only contract) and **audits** the result
  with sanitized fields only.

Every caller — the in-box bootstrap, the operator management command, and the
DRF authoring endpoint — uses :func:`register_pack`; there is no privileged code
path for the in-box catalog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import IntegrityError, transaction

from cms.exceptions import CMSError
from cms.models import AcesPackageSource
from cms.scenarios.legacy_ids import ScenarioIdCollisionError, ensure_scenario_id_available
from cms.scenarios.pack_validation import (
    PackDigestError,
    PackValidationError,
    validate_pack,
    verify_pack_digest,
)
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.auth import validate_cms_authoring_user
from shared.log_sanitize import safe_log_value
from shared.schemas.aces_package_source import AcesPackageSourceError

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

_OBJECT_SOURCE_KIND = "object"

# Registration is not conformance. Conformance ("passed") is a trust fact
# established by a separate, trusted conformance process (the ACES conformance
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
        CMSError: on legacy-id shadowing, duplicate id, an invalid pack, a
            scenario_id that does not match the pack's validated identity, or an
            invalid reference record.
    """
    validate_cms_authoring_user(user, "register_pack")
    try:
        ensure_scenario_id_available(request.scenario_id, registering="pack")
    except ScenarioIdCollisionError as exc:
        raise CMSError(str(exc)) from exc
    existing = AcesPackageSource.objects.filter(scenario_id=request.scenario_id).first()
    if existing is not None:
        return _reuse_existing(existing, request, idempotent=idempotent)
    _bind_scenario_id_to_pack_identity(request)

    try:
        with transaction.atomic():
            row = AcesPackageSource.objects.create(
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
    except AcesPackageSourceError as exc:
        # Reference-shape violation from the model's provenance-only validator.
        raise CMSError("Invalid pack reference") from exc
    except IntegrityError as exc:
        if idempotent:
            raced = AcesPackageSource.objects.filter(scenario_id=request.scenario_id).first()
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


def _reuse_existing(
    row: AcesPackageSource,
    request: PackRegistrationRequest,
    *,
    idempotent: bool,
) -> RegisteredPack:
    """Return an exact idempotent retry or reject duplicate/drifted identity."""
    if not idempotent:
        raise CMSError(f"A pack with id '{request.scenario_id}' is already registered")
    persisted = (
        row.source_kind,
        row.contract_kind,
        row.contract_profile,
        row.package_ref,
        row.package_version,
        row.package_digest,
        row.lock_ref,
        row.lock_digest,
        row.provenance,
    )
    requested = (
        request.source_kind,
        request.contract_kind,
        request.contract_profile,
        request.package_ref,
        request.package_version,
        request.package_digest,
        request.lock_ref,
        request.lock_digest,
        dict(request.provenance or {}),
    )
    if persisted != requested:
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
    digest MUST match the canonical ACES associated-artifact identity. Staging
    is required to remain immutable; launch repeats the byte binding immediately
    before SDL load so a later replacement fails closed.

    Object-backed packs are not resolved here: they have no containment-checked
    local resolution until #1567 and are kept non-launchable, so both their
    content validation and their identity binding are deferred with that resolver
    rather than run against an unavailable artifact.
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
    root = Path(settings.ACES_PACKAGE_ROOT).resolve()
    candidate = (root / package_ref).resolve()
    if candidate != root and root not in candidate.parents:
        raise CMSError("package_ref escapes the configured package root")
    return candidate


def _audit_registration(row: AcesPackageSource, user: User, request_id: str) -> None:
    """Record the sanitized registration audit as a fail-closed safety control."""
    try:
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.SCENARIO,
                # AcesPackageSource PKs are UUIDs; existing scenario audit records
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
