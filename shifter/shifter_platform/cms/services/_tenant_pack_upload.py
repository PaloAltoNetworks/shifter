"""Tenant-owned immutable pack upload through the existing registration contract."""

from __future__ import annotations

import json
import logging
import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import yaml
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from cms.models import RaesPackageSource, ScenarioModelNeeds
from cms.scenarios.pack_validation import pack_digest, validate_pack
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent, audit_log
from shared.cloud import get_object_storage
from shared.exceptions import ValidationError
from shared.model_access import PackModelNeedsDeclaration
from shared.raes.object_source import stage_uploaded_pack
from shared.raes.pack_conformance import validate_pack_contract
from shared.raes.package_loader import resolve_pack_scenario_path
from workspaces.services import get_organization_profile

from ._content_ingestion import PackRegistrationRequest, register_pack

logger = logging.getLogger(__name__)
_MODEL_NEEDS_FILE = "model-needs.json"
_MODEL_NEEDS_MAX_BYTES = 65_536


def _pack_model_needs(root: Path, digest: str) -> dict[str, dict[str, object]]:
    """Bind an optional closed pack declaration to the verified archive digest."""
    path = root / _MODEL_NEEDS_FILE
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size > _MODEL_NEEDS_MAX_BYTES:
        raise ValueError("Pack model needs exceed their bound")
    try:
        declaration = PackModelNeedsDeclaration.model_validate(json.loads(path.read_text(encoding="utf-8")))
        return declaration.bind_to_digest(digest)
    except Exception:
        raise ValueError("Pack model needs are invalid") from None


def _validate_archive(path: Path, name: str, report: str) -> tuple[str, str, dict[str, dict[str, object]]]:
    """Verify bounded archive contents and return their digest and package version."""
    with stage_uploaded_pack(
        path,
        expected_pack_name=name,
        max_archive_bytes=settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES,
        max_uncompressed_bytes=settings.RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES,
        max_entries=settings.RAES_PACKAGE_MAX_ENTRIES,
    ) as root:
        if validate_pack(root) != name:
            raise ValueError("Pack identity mismatch")
        metadata_path = root / "pack.yaml"
        if metadata_path.stat().st_size > 65_536:
            raise ValueError("Pack metadata exceeds its bound")
        metadata = yaml.safe_load(metadata_path.read_text())
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+!-]{0,127}", version):
            raise ValueError("Pack version is invalid")
        digest = pack_digest(root)
        validate_pack_contract(resolve_pack_scenario_path(root), report)
        return digest, version, _pack_model_needs(root, digest)


def _persist(
    user: User,
    organization_uuid: UUID,
    request: PackRegistrationRequest,
    report: str,
    request_id: str,
    model_needs: dict[str, dict[str, object]],
) -> dict[str, Any]:
    """Register validated bytes and their conformance evidence atomically."""
    with transaction.atomic():
        # Reauthorize after foreign-input validation and storage I/O.
        get_organization_profile(user, organization_uuid)
        result = register_pack(
            user=user,
            request=request,
            organization_uuid=organization_uuid,
            request_id=request_id,
        )
        row = RaesPackageSource.objects.select_for_update().get(scenario_id=result.scenario_id)
        row.conformance_status = "passed"
        row.conformance_report_ref = report
        row.save(update_fields=["conformance_status", "conformance_report_ref", "updated_at"])
        if model_needs:
            overlay = ScenarioModelNeeds.objects.select_for_update().filter(scenario_id=row.scenario_id).first()
            if overlay is None:
                overlay = ScenarioModelNeeds(scenario_id=row.scenario_id, updated_by=user)
            overlay.authored_package_digest = row.package_digest
            overlay.needs = model_needs
            overlay.updated_by = user
            overlay.save()
        else:
            ScenarioModelNeeds.objects.filter(scenario_id=row.scenario_id).delete()
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.SCENARIO,
                entity_id=0,
                entity_ref=row.scenario_id,
                action=AuditAction.UPDATE,
                actor_type=AuditActorType.USER,
                actor_id=user.id,
                request_id=request_id,
                new_state={
                    "organization_uuid": str(organization_uuid),
                    "package_digest": row.package_digest,
                    "conformance_status": "passed",
                    "conformance_report_ref": report,
                },
            ),
            strict=True,
        )
        return {
            **asdict(result),
            "name": row.package_identity,
            "package_version": row.package_version,
            "package_digest": row.package_digest,
            "conformance_status": row.conformance_status,
        }


def _write_archive(archive: UploadedFile, path: Path) -> None:
    """Copy upload chunks while enforcing the archive byte limit."""
    size = 0
    with path.open("wb") as stream:
        for chunk in archive.chunks():
            size += len(chunk)
            if size > settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES:
                raise ValueError("Archive exceeds its bound")
            stream.write(chunk)


def upload_tenant_pack(
    *,
    user: User,
    organization_uuid: UUID,
    name: str,
    archive: UploadedFile,
    expected_digest: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    """Validate bytes before storing; never execute, install, or select an adapter."""
    organization_uuid = get_organization_profile(user, organization_uuid).uuid
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name):
        raise ValidationError("Enter a valid pack name")
    if expected_digest and not re.fullmatch(r"sha256:[a-f0-9]{64}", expected_digest):
        raise ValidationError("The expected pack version is invalid")
    bucket = settings.RAES_PACKAGE_BUCKET
    if not bucket:
        raise ValidationError("Pack storage is unavailable")
    prefix = settings.RAES_PACKAGE_PREFIX.strip("/")
    catalog_id = "pack-" + uuid5(organization_uuid, name).hex
    report = "urn:shifter:pack-conformance:" + str(uuid4())
    with tempfile.TemporaryDirectory(prefix="tenant-pack-upload-") as directory:
        path = Path(directory) / "archive"
        try:
            _write_archive(archive, path)
            digest, version, model_needs = _validate_archive(path, name, report)
        except Exception:
            raise ValidationError("The pack archive failed validation; check its name, content and size") from None
        reference = f"tenant-packs/{organization_uuid}/{uuid4()}.tar.gz"
        key = f"{prefix}/{reference}" if prefix else reference
        storage = get_object_storage()
        # Unique server-owned object identity: rollback cannot remove another
        # upload or a previously committed pack revision.
        try:
            with path.open("rb") as stream:
                storage.upload_file(stream, bucket, key, content_type="application/gzip")
            return _persist(
                user,
                organization_uuid,
                PackRegistrationRequest(
                    scenario_id=catalog_id,
                    package_name=name,
                    source_kind="object",
                    contract_kind="raes",
                    contract_profile="shifter",
                    package_ref=reference,
                    package_version=version,
                    package_digest=digest,
                    expected_package_digest=expected_digest,
                ),
                report,
                request_id,
                model_needs,
            )
        except Exception:
            try:
                storage.delete_object(bucket, key)
            except Exception:
                logger.error("Uncommitted pack upload cleanup failed")
            raise ValidationError("Pack installation failed; reload the current version and retry") from None
