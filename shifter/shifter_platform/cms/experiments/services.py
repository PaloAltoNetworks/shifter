"""Experiment manager business logic.

All business logic lives here. Views call services, services call models/S3.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from cms.assets.s3 import S3Error
from cms.experiments.exceptions import (
    ArtifactError,
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.models import (
    Experiment,
    ExperimentRun,
    ExperimentScript,
    RunArtifact,
    ScriptAsset,
)
from cms.experiments.s3 import (
    delete_s3_object,
    generate_presigned_download_url,
    generate_script_upload_url,
    generate_upload_token,
    verify_s3_object,
    verify_upload_token,
)
from cms.experiments.schemas import (
    ExperimentCreateInput,
    ExperimentStatus,
    RunStatus,
    ScriptUploadInput,
)
from cms.scenarios.loader import load_scenario

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)


# =============================================================================
# Script Asset services
# =============================================================================


def list_scripts(user: User) -> QuerySet[ScriptAsset]:
    """List active (non-deleted) scripts for a user.

    Args:
        user: The authenticated user.

    Returns:
        QuerySet of active ScriptAsset objects.
    """
    return ScriptAsset.objects.filter(user=user, deleted_at__isnull=True).order_by("-created_at")


def initiate_script_upload(user: User, name: str, filename: str, file_size: int) -> dict:
    """Start the script upload flow: validate, generate presigned URL, return token.

    Args:
        user: The authenticated user.
        name: User-provided script name.
        filename: Original filename.
        file_size: Expected file size in bytes.

    Returns:
        Dict with presigned_url, s3_key, upload_token.

    Raises:
        ScriptUploadError: If validation or URL generation fails.
    """
    try:
        validated = ScriptUploadInput(name=name, filename=filename, file_size=file_size)
    except Exception as e:
        logger.warning("initiate_script_upload: validation failed user_id=%s: %s", user.pk, e)
        raise ScriptUploadError(f"Validation failed: {e}") from e

    try:
        presigned_url, s3_key = generate_script_upload_url(user.pk, validated.filename)
    except S3Error as e:
        logger.error("initiate_script_upload: S3 error user_id=%s: %s", user.pk, e)
        raise ScriptUploadError(f"Failed to generate upload URL: {e}") from e

    upload_token = generate_upload_token(
        user_id=user.pk,
        s3_key=s3_key,
        name=validated.name,
        filename=validated.filename,
        file_size=validated.file_size,
    )

    logger.info("initiate_script_upload: success user_id=%s s3_key=%s", user.pk, s3_key)
    return {
        "presigned_url": presigned_url,
        "s3_key": s3_key,
        "upload_token": upload_token,
    }


def complete_script_upload(user: User, upload_token: str) -> ScriptAsset:
    """Finalize script upload: verify token, verify S3 object, create DB record.

    Args:
        user: The authenticated user.
        upload_token: HMAC-signed upload token from initiate step.

    Returns:
        Created ScriptAsset instance.

    Raises:
        ScriptUploadError: If verification fails.
    """
    try:
        payload = verify_upload_token(upload_token, user.pk)
    except ValueError as e:
        logger.warning("complete_script_upload: token invalid user_id=%s: %s", user.pk, e)
        raise ScriptUploadError(f"Invalid upload token: {e}") from e

    s3_key = payload["s3_key"]

    try:
        actual_size, etag = verify_s3_object(s3_key)
    except S3Error as e:
        logger.error("complete_script_upload: S3 verify failed s3_key=%s: %s", s3_key, e)
        raise ScriptUploadError(f"Upload verification failed: {e}") from e

    max_size = settings.SCRIPT_MAX_FILE_SIZE_BYTES
    if actual_size > max_size:
        logger.warning(
            "complete_script_upload: file too large s3_key=%s size=%d max=%d",
            s3_key,
            actual_size,
            max_size,
        )
        delete_s3_object(s3_key)
        raise ScriptUploadError(f"File size {actual_size} exceeds maximum {max_size} bytes")

    script = ScriptAsset.objects.create(
        user=user,
        name=payload["name"],
        s3_key=s3_key,
        original_filename=payload["filename"],
        file_size_bytes=actual_size,
        sha256_hash=etag,
    )

    logger.info(
        "complete_script_upload: created script_id=%s user_id=%s s3_key=%s",
        script.pk,
        user.pk,
        s3_key,
    )
    return script


def delete_script(user: User, script_id: int) -> None:
    """Soft-delete a script asset.

    Args:
        user: The authenticated user.
        script_id: ID of the script to delete.

    Raises:
        ScriptUploadError: If script not found or not owned by user.
    """
    try:
        script = ScriptAsset.objects.get(pk=script_id, user=user, deleted_at__isnull=True)
    except ScriptAsset.DoesNotExist:
        logger.warning("delete_script: not found script_id=%s user_id=%s", script_id, user.pk)
        raise ScriptUploadError("Script not found") from None

    script.deleted_at = timezone.now()
    script.save(update_fields=["deleted_at"])
    logger.info("delete_script: soft-deleted script_id=%s user_id=%s", script_id, user.pk)


# =============================================================================
# Experiment services
# =============================================================================


def list_experiments(user: User) -> QuerySet[Experiment]:
    """List experiments for a user.

    Args:
        user: The authenticated user.

    Returns:
        QuerySet of Experiment objects with run counts annotated.
    """
    from django.db.models import Count, Q

    return (
        Experiment.objects.filter(user=user)
        .annotate(
            completed_runs=Count("runs", filter=Q(runs__status=RunStatus.COMPLETED.value)),
            total_run_count=Count("runs"),
        )
        .order_by("-created_at")
    )


def get_experiment(user: User, experiment_id: int) -> Experiment:
    """Get a single experiment with related data.

    Args:
        user: The authenticated user.
        experiment_id: ID of the experiment.

    Returns:
        Experiment instance with prefetched runs and scripts.

    Raises:
        ExperimentError: If not found.
    """
    try:
        return Experiment.objects.prefetch_related("runs__artifacts", "scripts__script").get(
            pk=experiment_id, user=user
        )
    except Experiment.DoesNotExist:
        logger.warning("get_experiment: not found experiment_id=%s user_id=%s", experiment_id, user.pk)
        raise ExperimentError("Experiment not found") from None


def create_experiment(user: User, data: ExperimentCreateInput) -> Experiment:
    """Create an experiment with script assignments.

    Args:
        user: The authenticated user.
        data: Validated experiment creation input.

    Returns:
        Created Experiment instance.

    Raises:
        ExperimentValidationError: If scenario or scripts are invalid.
    """
    # Validate scenario exists
    try:
        scenario = load_scenario(data.scenario_id)
    except ValueError as e:
        logger.warning("create_experiment: invalid scenario_id=%s: %s", data.scenario_id, e)
        raise ExperimentValidationError(f"Invalid scenario: {e}") from e

    # Validate script assignments reference real instances
    instance_names = {inst.name for inst in scenario.instances}
    for script_input in data.scripts:
        if script_input.instance_name not in instance_names:
            raise ExperimentValidationError(
                f"Instance '{script_input.instance_name}' not found in scenario '{data.scenario_id}'"
            )

    # Validate referenced script assets exist and belong to user
    script_ids = [s.script_id for s in data.scripts if s.script_id]
    if script_ids:
        existing_scripts = set(
            ScriptAsset.objects.filter(
                pk__in=script_ids,
                user=user,
                deleted_at__isnull=True,
            ).values_list("pk", flat=True)
        )
        missing = set(script_ids) - existing_scripts
        if missing:
            raise ExperimentValidationError(f"Script(s) not found: {missing}")

    # Validate agent exists if specified
    agent = None
    if data.agent_id:
        from cms.models import AgentConfig

        try:
            agent = AgentConfig.objects.get(pk=data.agent_id, user=user, deleted_at__isnull=True)
        except AgentConfig.DoesNotExist:
            raise ExperimentValidationError(f"Agent not found: {data.agent_id}") from None

    with transaction.atomic():
        experiment = Experiment.objects.create(
            user=user,
            name=data.name,
            description=data.description,
            scenario_id=data.scenario_id,
            agent=agent,
            total_runs=data.total_runs,
            max_parallel_runs=data.max_parallel_runs,
        )

        for script_input in data.scripts:
            ExperimentScript.objects.create(
                experiment=experiment,
                instance_name=script_input.instance_name,
                script_type=script_input.script_type.value,
                script_id=script_input.script_id,
                claude_prompt=script_input.claude_prompt or "",
                execution_order=script_input.execution_order,
            )

    logger.info(
        "create_experiment: created experiment_id=%s user_id=%s scenario=%s runs=%d",
        experiment.pk,
        user.pk,
        data.scenario_id,
        data.total_runs,
    )
    return experiment


def start_experiment(user: User, experiment_id: int) -> Experiment:
    """Queue an experiment for execution.

    Transitions from DRAFT to QUEUED and creates ExperimentRun records.

    Args:
        user: The authenticated user.
        experiment_id: ID of the experiment.

    Returns:
        Updated Experiment instance.

    Raises:
        ExperimentError: If not found.
        ExperimentStateError: If not in DRAFT state.
    """
    try:
        experiment = Experiment.objects.get(pk=experiment_id, user=user)
    except Experiment.DoesNotExist:
        raise ExperimentError("Experiment not found") from None

    if experiment.status != ExperimentStatus.DRAFT.value:
        raise ExperimentStateError(f"Experiment must be in draft state to start (currently {experiment.status})")

    with transaction.atomic():
        # Create run records
        runs = [ExperimentRun(experiment=experiment, run_number=i) for i in range(1, experiment.total_runs + 1)]
        ExperimentRun.objects.bulk_create(runs)

        # Transition to queued
        experiment.transition_to(ExperimentStatus.QUEUED)

    logger.info(
        "start_experiment: queued experiment_id=%s user_id=%s total_runs=%d",
        experiment_id,
        user.pk,
        experiment.total_runs,
    )
    return experiment


def cancel_experiment(user: User, experiment_id: int) -> Experiment:
    """Cancel a running experiment.

    Args:
        user: The authenticated user.
        experiment_id: ID of the experiment.

    Returns:
        Updated Experiment instance.

    Raises:
        ExperimentError: If not found.
        ExperimentStateError: If not in a cancellable state.
    """
    try:
        experiment = Experiment.objects.get(pk=experiment_id, user=user)
    except Experiment.DoesNotExist:
        raise ExperimentError("Experiment not found") from None

    if experiment.status not in {ExperimentStatus.QUEUED.value, ExperimentStatus.RUNNING.value}:
        raise ExperimentStateError(f"Cannot cancel experiment in {experiment.status} state")

    experiment.transition_to(ExperimentStatus.CANCELLED)
    logger.info("cancel_experiment: cancelled experiment_id=%s user_id=%s", experiment_id, user.pk)
    return experiment


# =============================================================================
# Artifact services
# =============================================================================


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
    try:
        artifact = RunArtifact.objects.select_related("run__experiment").get(
            pk=artifact_id,
            run__experiment_id=experiment_id,
            run__experiment__user=user,
        )
    except RunArtifact.DoesNotExist:
        raise ArtifactError("Artifact not found") from None

    try:
        url = generate_presigned_download_url(artifact.s3_key)
    except S3Error as e:
        logger.error("get_artifact_download_url: failed artifact_id=%s: %s", artifact_id, e)
        raise ArtifactError(f"Failed to generate download URL: {e}") from e

    logger.info("get_artifact_download_url: artifact_id=%s user_id=%s", artifact_id, user.pk)
    return url


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
    from cms.experiments.models import ExperimentArtifact

    try:
        bundle = ExperimentArtifact.objects.select_related("experiment").get(
            experiment_id=experiment_id,
            experiment__user=user,
        )
    except ExperimentArtifact.DoesNotExist:
        raise ArtifactError("Experiment bundle not found") from None

    try:
        url = generate_presigned_download_url(bundle.s3_key)
    except S3Error as e:
        logger.error("get_bundle_download_url: failed experiment_id=%s: %s", experiment_id, e)
        raise ArtifactError(f"Failed to generate download URL: {e}") from e

    logger.info("get_bundle_download_url: experiment_id=%s user_id=%s", experiment_id, user.pk)
    return url


# =============================================================================
# Scenario helpers
# =============================================================================


def get_scenario_instances(scenario_id: str) -> list[dict]:
    """Get instance list for a scenario template.

    Args:
        scenario_id: Scenario template ID.

    Returns:
        List of dicts with instance name and role.

    Raises:
        ExperimentValidationError: If scenario not found.
    """
    try:
        scenario = load_scenario(scenario_id)
    except ValueError as e:
        raise ExperimentValidationError(f"Invalid scenario: {e}") from e

    return [{"name": inst.name, "role": inst.role, "os_type": inst.os_type} for inst in scenario.instances]
