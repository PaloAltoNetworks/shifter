"""Resolve digest-pinned native CTF content through provider-neutral storage."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

from ctf.content_bundle import CtfContentBundle, CtfContentBundleError, parse_ctf_content_bundle
from ctf.exceptions import CTFValidationError
from shared.log_sanitize import safe_log_value
from shared.schemas.ctf_content_reference import REFERENCE_CONTRACT, CtfContentReference

logger = logging.getLogger(__name__)
_RESOLUTION_ERROR = "Scenario CTF content could not be resolved."


@dataclass(frozen=True)
class HydrationSourceEvidence:
    """Bounded source evidence persisted with a successful hydration."""

    reference_contract: str
    declared_digest: str
    object_key_fingerprint: str
    object_identity_fingerprint: str
    object_size_bytes: int


@dataclass(frozen=True)
class ResolvedCtfContent:
    """Trusted bundle and bounded evidence returned by the resolver."""

    bundle: CtfContentBundle
    evidence: HydrationSourceEvidence


def _fingerprint(value: object) -> str:
    """Return a stable SHA-256 fingerprint for bounded evidence."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bounded_identity(identity: dict[str, Any]) -> dict[str, object]:
    """Select non-secret object identity fields for a stable fingerprint."""
    return {
        key: identity[key]
        for key in ("content_length", "etag", "generation", "version_id")
        if key in identity and isinstance(identity[key], (str, int))
    }


def _read_download(path: Path, *, max_bytes: int) -> bytes:
    """Read a downloaded object while enforcing the deployment byte limit."""
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise CTFValidationError(
            _RESOLUTION_ERROR,
            code="CTF_CONTENT_TOO_LARGE",
        )
    return raw


def _resolve_reference(reference: CtfContentReference) -> ResolvedCtfContent:
    """Resolve, verify, and parse one digest-pinned object reference."""
    from shared.cloud import get_object_storage
    from shared.cloud.exceptions import CloudStorageError, ObjectPreconditionError

    bucket = str(getattr(settings, "CTF_CONTENT_BUCKET", "") or "").strip()
    max_bytes = int(getattr(settings, "CTF_CONTENT_MAX_BYTES", 0) or 0)
    if not bucket or max_bytes <= 0:
        raise CTFValidationError(
            "Scenario CTF content is not configured.",
            code="CTF_CONTENT_NOT_CONFIGURED",
        )

    storage = get_object_storage()
    staging = Path(tempfile.mkdtemp(prefix="ctf-content-"))
    try:
        destination = staging / "bundle.json"
        try:
            identity = storage.head_object(bucket, reference.object_key)
            declared_size = int(identity.get("content_length", 0) or 0)
            if declared_size < 0 or declared_size > max_bytes:
                raise CTFValidationError(
                    _RESOLUTION_ERROR,
                    code="CTF_CONTENT_TOO_LARGE",
                )
            realized_identity = storage.download_object(
                bucket,
                reference.object_key,
                str(destination),
                max_bytes=max_bytes,
                expected_identity=identity,
            )
        except ObjectPreconditionError as exc:
            raise CTFValidationError(
                "Scenario CTF content changed during retrieval.",
                code="CTF_CONTENT_CHANGED",
            ) from exc
        except CloudStorageError as exc:
            raise CTFValidationError(
                _RESOLUTION_ERROR,
                code="CTF_CONTENT_RESOLUTION_FAILED",
            ) from exc

        raw = _read_download(destination, max_bytes=max_bytes)
        actual_digest = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        if actual_digest != reference.digest:
            raise CTFValidationError(
                "Scenario CTF content failed integrity verification.",
                code="CTF_CONTENT_DIGEST_MISMATCH",
            )
        try:
            bundle = parse_ctf_content_bundle(raw)
        except CtfContentBundleError as exc:
            raise CTFValidationError(
                "Scenario CTF content is invalid.",
                code="CTF_CONTENT_INVALID",
            ) from exc

        evidence = HydrationSourceEvidence(
            reference_contract=REFERENCE_CONTRACT,
            declared_digest=reference.digest,
            object_key_fingerprint=_fingerprint(reference.object_key),
            object_identity_fingerprint=_fingerprint(_bounded_identity(realized_identity)),
            object_size_bytes=len(raw),
        )
        return ResolvedCtfContent(bundle=bundle, evidence=evidence)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def resolve_scenario_ctf_content(scenario_id: str) -> ResolvedCtfContent | None:
    """Resolve configured content for ``scenario_id``; return ``None`` when absent."""
    references = settings.CTF_CONTENT_REFERENCES
    reference = references.get(scenario_id)
    if reference is None:
        return None
    logger.info("Resolving native CTF content for scenario %s", safe_log_value(scenario_id))
    resolved = _resolve_reference(reference)
    if resolved.bundle.scenario_id != scenario_id:
        raise CTFValidationError(
            "Scenario CTF content does not match the selected scenario.",
            code="CTF_CONTENT_SCENARIO_MISMATCH",
        )
    return resolved


__all__ = [
    "HydrationSourceEvidence",
    "ResolvedCtfContent",
    "resolve_scenario_ctf_content",
]
