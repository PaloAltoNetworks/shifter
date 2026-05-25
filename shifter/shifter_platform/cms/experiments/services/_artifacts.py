"""Artifact download URL service entrypoints."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.assets.s3 import S3Error
from cms.experiments import services as _pkg
from cms.experiments.exceptions import ArtifactError, ExperimentError

from ._common import _validate_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def get_artifact_download_url(user: User, experiment_id: int, artifact_id: int) -> str:
    """Generate a presigned download URL for a run artifact.

    Args:
        user: The authenticated user.
        experiment_id: ID of the experiment.
        artifact_id: ID of the artifact.

    Returns:
        Presigned download URL.

    Raises:
        ArtifactError: If artifact not found or access denied.
    """
    _validate_user(user, "get_artifact_download_url")
    # Coerce user-controlled ids through ``int()`` at the boundary so CodeQL
    # sees a primitive-int barrier between user input and the log statements.
    experiment_id = int(experiment_id)
    artifact_id = int(artifact_id)
    logger.debug(
        "get_artifact_download_url called for user_id=%s experiment_id=%d artifact_id=%d",
        user.id,
        experiment_id,
        artifact_id,
    )
    try:
        try:
            artifact = _pkg.RunArtifact.objects.select_related("run__experiment").get(
                pk=artifact_id,
                run__experiment_id=experiment_id,
                run__experiment__user=user,
            )
        except _pkg.RunArtifact.DoesNotExist:
            raise ArtifactError("Artifact not found or you don't have access") from None
        _pkg._check_result_type(artifact, _pkg.RunArtifact, "get_artifact_download_url")

        try:
            url = _pkg.generate_presigned_download_url(artifact.s3_key)
        except S3Error as e:
            logger.exception("get_artifact_download_url: failed artifact_id=%d", artifact_id)
            raise ArtifactError(f"Failed to generate download URL: {e}") from e

        logger.info("get_artifact_download_url: artifact_id=%d user_id=%s", artifact_id, user.pk)
        return url
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in get_artifact_download_url for user_id=%s", user.id)
        raise


def get_bundle_download_url(user: User, experiment_id: int) -> str:
    """Generate a presigned download URL for the experiment bundle.

    Args:
        user: The authenticated user.
        experiment_id: ID of the experiment.

    Returns:
        Presigned download URL.

    Raises:
        ArtifactError: If bundle not found.
    """
    _validate_user(user, "get_bundle_download_url")
    # Coerce user-controlled id through ``int()`` at the boundary so CodeQL
    # sees a primitive-int barrier between user input and the log statements.
    experiment_id = int(experiment_id)
    logger.debug("get_bundle_download_url called for user_id=%s experiment_id=%d", user.id, experiment_id)
    try:
        try:
            bundle = _pkg.ExperimentArtifact.objects.select_related("experiment").get(
                experiment_id=experiment_id,
                experiment__user=user,
            )
        except _pkg.ExperimentArtifact.DoesNotExist:
            raise ArtifactError("Experiment bundle not found or you don't have access") from None
        _pkg._check_result_type(bundle, _pkg.ExperimentArtifact, "get_bundle_download_url")

        try:
            url = _pkg.generate_presigned_download_url(bundle.s3_key)
        except S3Error as e:
            logger.exception("get_bundle_download_url: failed experiment_id=%d", experiment_id)
            raise ArtifactError(f"Failed to generate download URL: {e}") from e

        logger.info("get_bundle_download_url: experiment_id=%d user_id=%s", experiment_id, user.pk)
        return url
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in get_bundle_download_url for user_id=%s", user.id)
        raise
