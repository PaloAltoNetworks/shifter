"""Single-flight acquisition of backend-owned feature artifacts (ADR-034-R11, R12).

``request_acquisition`` is called wherever an artifact is needed (pack
registration, deploy bootstrap, launch). Under a row lock it reuses a ready
artifact, joins an in-flight attempt, respects a short failure backoff, or claims
one fresh attempt. It never launches anything itself: the provisioner launcher's
``reconcile_feature_artifact_acquisitions`` creates exactly one isolated Job per
claimed attempt, reads its result, verifies the stored object independently, and
finalizes the row. Only the attempt holding the row's current ``attempt_id`` may
complete or fail it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from shared.cloud.exceptions import CloudStorageError
from shared.feature_artifacts.job import AcquisitionResult
from shared.feature_artifacts.recipes import NpmBinaryRecipe, RecipeError, recipe_for
from shared.raes.content_delivery import normalized_storage_key

if TYPE_CHECKING:
    from engine.models import AcquiredFeatureArtifact
    from shared.cloud.types import ObjectStorage

logger = logging.getLogger(__name__)

# Must outlast the acquisition Job's active deadline (30 minutes) so a running Job's
# row is never reclaimed underneath it.
ATTEMPT_LEASE = timedelta(minutes=35)
FAILURE_BACKOFF = timedelta(seconds=60)

# AcquiredFeatureArtifact.State values (models load lazily: engine.services is
# imported before the app registry is ready).
_ACQUIRING, _READY, _FAILED = "acquiring", "ready", "failed"


def _model() -> type[AcquiredFeatureArtifact]:
    """The inventory model, imported lazily (engine.services loads before the app registry)."""
    from engine.models import AcquiredFeatureArtifact

    return AcquiredFeatureArtifact


class FeatureArtifactUnavailableError(RuntimeError):
    """A declared feature artifact cannot be made ready for this range."""


@dataclass(frozen=True)
class ArtifactRequest:
    """One feature artifact a scenario declares, before version resolution."""

    source_name: str
    version: str
    platform: str


@dataclass(frozen=True)
class StorageTarget:
    """Where acquired bytes live: the existing content-addressed delivery location."""

    storage: ObjectStorage
    bucket: str
    prefix: str


def _resolve(request: ArtifactRequest) -> tuple[NpmBinaryRecipe, str]:
    """The request's recipe and resolved exact version; raises ``RecipeError``."""
    recipe = recipe_for(request.source_name)
    recipe.package_for(request.platform)
    return recipe, recipe.resolve_version(request.version)


def _object_matches(target: StorageTarget, key: str, byte_count: int) -> bool:
    """The stored object exists with exactly the expected size.

    Only a definite absence is ``False``; a storage error (denied, throttled,
    unreachable) propagates rather than masquerading as a missing object.
    """
    if not key or not target.storage.object_exists(target.bucket, key):
        return False
    meta = target.storage.head_object(target.bucket, key)
    return int(meta.get("content_length", -1)) == byte_count


def _claim(row: AcquiredFeatureArtifact, now: datetime) -> None:
    """Start a fresh attempt on ``row`` (caller holds its row lock)."""
    row.state = _ACQUIRING
    row.attempt_id = uuid4()
    row.attempt_started_at = now
    row.attempt_expires_at = now + ATTEMPT_LEASE
    row.failure_reason = ""
    row.retry_not_before = None
    row.save()


def request_acquisition(request: ArtifactRequest, *, target: StorageTarget) -> AcquiredFeatureArtifact:
    """Ensure the artifact is ready or being acquired; never two attempts at once.

    Raises :class:`RecipeError` when no platform recipe can satisfy the request.
    """
    recipe, version = _resolve(request)
    now = timezone.now()
    with transaction.atomic():
        row, _created = (
            _model()
            .objects.select_for_update()
            .get_or_create(
                source_name=request.source_name,
                resolved_version=version,
                platform=request.platform,
                defaults={
                    "recipe_id": recipe.recipe_id,
                    "payload_kind": recipe.payload_kind,
                    "install_policy": recipe.install_policy,
                    "state": _FAILED,
                },
            )
        )
        if row.state == _READY and _object_matches(target, row.storage_key, row.byte_count or 0):
            return row
        in_flight = row.state == _ACQUIRING and row.attempt_expires_at and row.attempt_expires_at > now
        backing_off = row.state == _FAILED and row.retry_not_before and row.retry_not_before > now
        if not (in_flight or backing_off):
            _claim(row, now)
            logger.info("feature artifact acquisition claimed source=%s version=%s", request.source_name, version)
    return row


def _finish(row_id: UUID, attempt: UUID, **fields: Any) -> bool:
    """Write the attempt outcome only if this attempt still holds the row."""
    updated = (
        _model()
        .objects.filter(id=row_id, attempt_id=attempt, state=_ACQUIRING)
        .update(updated_at=timezone.now(), **fields)
    )
    return bool(updated)


def finalize_attempt(row_id: UUID, attempt: UUID, result: AcquisitionResult, *, target: StorageTarget) -> bool:
    """Apply a terminal Job result after verifying the stored object independently.

    The Job's report is not trusted on its own: a success must name the
    content-addressed key for its digest and that object must exist with the
    reported size. Returns ``False`` when the attempt no longer holds the row.
    """
    if result.ok:
        try:
            expected_key = normalized_storage_key(target.prefix, result.sha256)
        except Exception:
            expected_key = ""
        if (
            result.storage_key == expected_key
            and result.byte_count > 0
            and _object_matches(target, expected_key, result.byte_count)
        ):
            return _finish(
                row_id,
                attempt,
                state=_READY,
                storage_key=expected_key,
                sha256=result.sha256,
                byte_count=result.byte_count,
                upstream_ref=result.upstream_ref[:512],
                upstream_integrity=result.upstream_integrity[:128],
                acquired_at=timezone.now(),
            )
        result = AcquisitionResult(ok=False, reason="acquired object failed independent verification")
    return _finish(
        row_id,
        attempt,
        state=_FAILED,
        failure_reason=(result.reason or "feature artifact acquisition failed")[:256],
        retry_not_before=timezone.now() + FAILURE_BACKOFF,
    )


def await_ready(
    request: ArtifactRequest,
    *,
    target: StorageTarget,
    timeout: timedelta,
    poll: timedelta = timedelta(seconds=5),
    sleep: Callable[[float], None] = time.sleep,
) -> AcquiredFeatureArtifact:
    """Launch gate: return the ready artifact or fail this range (never other ranges).

    Requests acquisition (claiming a fresh attempt if none is usable), then waits
    up to ``timeout`` for the launcher to finish it. A failed attempt fails only
    the caller; a later caller starts a new attempt once the backoff elapses.
    """
    if transaction.get_connection().in_atomic_block:
        # The claim must commit before the launcher can see it; waiting inside an
        # open transaction would wait on an attempt that cannot start.
        raise RuntimeError("await_ready must not run inside a database transaction")
    try:
        _resolve(request)
    except RecipeError as exc:
        raise FeatureArtifactUnavailableError(str(exc)) from None
    deadline = timezone.now() + timeout
    seen_attempt: UUID | None = None
    while True:
        try:
            row = request_acquisition(request, target=target)
        except CloudStorageError as exc:
            raise FeatureArtifactUnavailableError("feature artifact storage could not be verified") from exc
        if row.state == _READY:
            return row
        if row.state == _ACQUIRING:
            seen_attempt = row.attempt_id
        elif seen_attempt is not None or row.retry_not_before is None:
            raise FeatureArtifactUnavailableError(row.failure_reason or "feature artifact acquisition failed")
        if timezone.now() >= deadline:
            raise FeatureArtifactUnavailableError("feature artifact acquisition did not complete in time")
        sleep(poll.total_seconds())
