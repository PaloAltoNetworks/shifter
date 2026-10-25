"""Provisioner-launcher reconciliation of feature-artifact acquisition Jobs (ADR-034-R12)."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from engine.services._feature_artifacts import StorageTarget, finalize_attempt
from shared.cloud import feature_artifact_jobs as jobs

if TYPE_CHECKING:
    from engine.models import AcquiredFeatureArtifact
    from shared.cloud.kubernetes import KubernetesTaskRunner

logger = logging.getLogger(__name__)

JOB_IMAGE_ENV = "FEATURE_ARTIFACT_JOB_IMAGE"


def default_storage_target() -> StorageTarget:
    """The deployment's content-addressed delivery location."""
    from shared.cloud import get_object_storage

    return StorageTarget(
        storage=get_object_storage(),
        bucket=settings.STORAGE_BUCKET_NAME,
        prefix=settings.RAES_CONTENT_DELIVERY_PREFIX,
    )


def _job_env() -> dict[str, str]:
    """The Job's whole environment: provider, delivery location and private scratch.

    AWS_REGION rides only when set (AWS): Kubernetes drops empty env values, which
    the acquisition admission policy would reject as value-less entries.
    """
    env = {
        "CLOUD_PROVIDER": str(getattr(settings, "CLOUD_PROVIDER", "")),
        "STORAGE_BUCKET_NAME": str(settings.STORAGE_BUCKET_NAME),
        "RAES_CONTENT_DELIVERY_PREFIX": str(settings.RAES_CONTENT_DELIVERY_PREFIX),
        "HOME": jobs.ACQUISITION_WORKDIR,
        "TMPDIR": jobs.ACQUISITION_WORKDIR,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    region = os.environ.get("AWS_REGION", "")
    if region:
        env["AWS_REGION"] = region
    return env


def reconcile_feature_artifact_acquisitions(
    *,
    limit: int = 3,
    image: str | None = None,
    target: StorageTarget | None = None,
    now: datetime | None = None,
    runner: KubernetesTaskRunner | None = None,
) -> int:
    """Launch, observe and finalize one isolated Job per in-flight attempt.

    No artifact is fetched in this process. A deployment without a configured
    acquisition Job image does nothing here, so its in-flight attempts expire and
    the ranges that need them fail materialization.
    """
    if not 1 <= limit <= 20:
        raise ValueError("Invalid feature-artifact reconciliation batch size")
    image = image if image is not None else os.environ.get(JOB_IMAGE_ENV, "")
    if not image:
        return 0
    from engine.models import AcquiredFeatureArtifact

    rows = list(
        AcquiredFeatureArtifact.objects.filter(
            state=AcquiredFeatureArtifact.State.ACQUIRING, attempt_expires_at__gt=now or timezone.now()
        ).order_by("attempt_started_at")[:limit]
    )
    target = target or (default_storage_target() if rows else None)
    for row in rows:
        _reconcile(row, image, target, runner)
    return len(rows)


def _reconcile(
    row: AcquiredFeatureArtifact, image: str, target: StorageTarget | None, runner: KubernetesTaskRunner | None
) -> None:
    """Advance one attempt: launch or observe its Job, then finalize and clean up."""
    attempt = row.attempt_id
    if attempt is None or target is None:
        return
    args = jobs.acquisition_args(row.source_name, row.resolved_version, row.platform)
    try:
        jobs.launch_acquisition(attempt, image=image, args=args, env=_job_env(), runner=runner)
        result = jobs.observe_acquisition(attempt, image=image, args=args, runner=runner)
        if result is None:
            return
        finalize_attempt(row.id, attempt, result, target=target)
        jobs.cleanup_acquisition(attempt, image=image, args=args, runner=runner)
    except Exception as exc:
        # Kubernetes and provider errors can carry diagnostics; log only the type.
        # The attempt stays leased and is retried next tick until it expires.
        logger.warning(
            "feature artifact acquisition reconcile deferred source=%s attempt=%s error=%s",
            row.source_name,
            attempt,
            type(exc).__name__,
        )
