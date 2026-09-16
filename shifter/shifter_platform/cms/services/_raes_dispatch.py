"""RAES pack resolution and dispatch helpers for the native launch path.

Split from ``_raes_range_create`` (python:S104 file-size gate): the repo/object
pack resolvers, the object-key joiner, and the canonical launch tail live here,
while ``_raes_range_create._dispatch_raes_package`` routes to them by source kind.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from cms.exceptions import CMSError

if TYPE_CHECKING:
    from uuid import UUID

    from django.contrib.auth.models import User

    from cms.models import RaesPackageSource
    from shared.range_instantiation_policy import BackendAdmission

logger = logging.getLogger(__name__)

_OBJECT_SOURCE_KIND = "object"


def dispatch_repo_raes_package(
    request_id: UUID,
    user: User,
    source: RaesPackageSource,
    backend_admission: BackendAdmission | None,
    workspace_id: int,
    egress_mode: str,
) -> None:
    """Resolve a repo pack under ``RAES_PACKAGE_ROOT``, verify its digest, launch."""
    from cms.scenarios.pack_validation import PackDigestError, verify_pack_digest
    from shared.raes.package_loader import RaesPackageError, resolve_pack_root

    try:
        pack_root = resolve_pack_root(source.package_ref, package_root=Path(settings.RAES_PACKAGE_ROOT))
    except RaesPackageError as exc:
        raise CMSError(f"RAES package could not be resolved: {exc}") from exc
    try:
        digest_matches = verify_pack_digest(pack_root, source.package_digest)
    except PackDigestError as exc:
        raise CMSError("RAES pack content identity could not be verified") from exc
    if not digest_matches:
        raise CMSError("RAES pack content digest no longer matches registration")
    _launch_pack(request_id, user, pack_root, backend_admission, workspace_id, egress_mode)


def dispatch_object_raes_package(
    request_id: UUID,
    user: User,
    source: RaesPackageSource,
    backend_admission: BackendAdmission | None,
    workspace_id: int,
    egress_mode: str,
) -> None:
    """Stage an object-backed pack, bind its identity + digest, then launch.

    Object rows are registered without content validation or digest binding
    (#1578), so this resolver provides the equivalent identity guarantees repo
    packs get (ADR-034-R5): it downloads the single immutable archive named by
    ``package_ref`` into a private temp dir, safely extracts it, re-runs the
    upstream pack contract validation, asserts the pack identity matches the
    registered ``scenario_id``, and verifies the canonical ``package_digest`` --
    all before SDL resolution, planning, or dispatch. The staged directory is
    always cleaned up by the resolver context manager.
    """
    from cms.scenarios.pack_validation import (
        PackDigestError,
        PackValidationError,
        validate_pack,
        verify_pack_digest,
    )
    from shared.cloud import get_object_storage
    from shared.raes.object_source import stage_object_pack
    from shared.raes.package_loader import RaesPackageError

    bucket = str(getattr(settings, "RAES_PACKAGE_BUCKET", "") or "").strip()
    if not bucket:
        raise CMSError("Object-backed RAES packages are not available: no package bucket is configured")

    try:
        with stage_object_pack(
            storage=get_object_storage(),
            bucket=bucket,
            key=_object_package_key(source.package_ref),
            max_archive_bytes=settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES,
            max_uncompressed_bytes=settings.RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES,
            max_entries=settings.RAES_PACKAGE_MAX_ENTRIES,
            expected_pack_name=source.scenario_id,
        ) as pack_root:
            try:
                validated_name = validate_pack(pack_root)
            except PackValidationError as exc:
                raise CMSError("RAES pack failed validation") from exc
            if validated_name != source.scenario_id:
                raise CMSError("RAES pack identity does not match the registered scenario")
            try:
                digest_matches = verify_pack_digest(pack_root, source.package_digest)
            except PackDigestError as exc:
                raise CMSError("RAES pack content identity could not be verified") from exc
            if not digest_matches:
                raise CMSError("RAES pack content digest no longer matches registration")
            _launch_pack(request_id, user, pack_root, backend_admission, workspace_id, egress_mode)
    except RaesPackageError as exc:
        raise CMSError(f"RAES object package could not be resolved: {exc}") from exc


def _object_package_key(package_ref: str) -> str:
    """Join the configured object-package prefix with the row's ``package_ref``."""
    prefix = str(getattr(settings, "RAES_PACKAGE_PREFIX", "") or "").strip().strip("/")
    ref = package_ref.strip().lstrip("/")
    return f"{prefix}/{ref}" if prefix else ref


def _launch_pack(
    request_id: UUID,
    user: User,
    pack_root: Path,
    backend_admission: BackendAdmission | None,
    workspace_id: int,
    egress_mode: str,
) -> None:
    """Select the single SDL entry, dispatch through the port, assert acceptance."""
    from cms.raes.dispatch import CmsRaesDispatchPort
    from shared.raes.package_loader import RaesPackageError, launch_raes_package, resolve_pack_scenario_path

    try:
        scenario_path = resolve_pack_scenario_path(pack_root)
    except RaesPackageError as exc:
        raise CMSError(f"RAES package could not be resolved: {exc}") from exc

    port = CmsRaesDispatchPort(
        user_id=user.id,
        request_id=str(request_id),
        backend_admission=backend_admission,
        pack_root=pack_root,
        workspace_id=workspace_id,
        egress_mode=egress_mode,
    )
    try:
        result = launch_raes_package(
            scenario_path=scenario_path, port=port, artifact_supply_provider=port.artifact_supply
        )
    except RaesPackageError as exc:
        raise CMSError(f"RAES package could not be launched: {exc}") from exc
    if not result.accepted:
        logger.warning("create_raes_native_range: dispatch not accepted request_id=%s", request_id)
        raise CMSError("RAES provisioning was not accepted")
