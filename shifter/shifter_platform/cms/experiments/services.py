"""Experiment manager business logic.

All business logic lives here. Views call services, services call models/S3.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from cms.assets.s3 import S3Error
from cms.experiments.events import publish_experiment_event
from cms.experiments.exceptions import (
    ArtifactError,
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
    ScriptUploadError,
)
from cms.experiments.models import (
    Experiment,
    ExperimentArtifact,
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
from cms.scenarios.registry import check_scenario_access, load_scenario_template
from risk_register.models import AuditLog
from risk_register.services import audit_log
from shared.auth import validate_cms_authoring_user
from shared.log_sanitize import safe_log

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet

logger = logging.getLogger(__name__)


def _validate_user(user: User, func_name: str) -> None:
    """Delegate to the shared CMS authoring user validator (see shared.auth)."""
    validate_cms_authoring_user(user, func_name)


def _check_result_type(result: object, expected_type: type, func_name: str) -> None:
    """Validate ORM return type — defensive check matching cms/services.py pattern."""
    if not isinstance(result, expected_type):
        logger.error(
            "%s: expected %s, got %s",
            func_name,
            expected_type.__name__,
            type(result).__name__,
        )
        raise TypeError(f"{func_name}: expected {expected_type.__name__}, got {type(result).__name__}")


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
    _validate_user(user, "list_scripts")
    logger.debug("list_scripts called for user_id=%s", user.id)
    try:
        return ScriptAsset.objects.filter(user=user).order_by("-created_at")
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in list_scripts for user_id=%s", user.id)
        raise


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
    _validate_user(user, "initiate_script_upload")
    logger.debug("initiate_script_upload called for user_id=%s filename=%s", user.id, filename)
    try:
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
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in initiate_script_upload for user_id=%s", user.id)
        raise


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
    _validate_user(user, "complete_script_upload")
    logger.debug("complete_script_upload called for user_id=%s", user.id)
    try:
        try:
            payload = verify_upload_token(upload_token, user.pk)
        except ValueError as e:
            logger.warning("complete_script_upload: token invalid user_id=%s: %s", user.pk, e)
            raise ScriptUploadError(f"Invalid upload token: {e}") from e

        s3_key = payload["s3_key"]

        try:
            actual_size, etag = verify_s3_object(s3_key)
        except S3Error as e:
            logger.error("complete_script_upload: S3 verify failed s3_key=%s: %s", safe_log(s3_key), safe_log(str(e)))
            raise ScriptUploadError(f"Upload verification failed: {e}") from e

        max_size = settings.SCRIPT_MAX_FILE_SIZE_BYTES
        if actual_size > max_size:
            logger.warning(
                "complete_script_upload: file too large s3_key=%s size=%d max=%d",
                safe_log(s3_key),
                actual_size,
                max_size,
            )
            delete_s3_object(s3_key)
            raise ScriptUploadError(f"File size {actual_size} exceeds maximum {max_size} bytes")

        script = ScriptAsset(
            user=user,
            name=payload["name"],
            s3_key=s3_key,
            original_filename=payload["filename"],
            file_size_bytes=actual_size,
            sha256_hash=etag,
        )
        try:
            script.full_clean()
        except DjangoValidationError as e:
            raise ScriptUploadError(f"Validation failed: {e}") from e
        script.save()

        audit_log(
            entity_type=AuditLog.EntityType.SCRIPT,
            entity_id=script.pk,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"name": payload["name"], "filename": payload["filename"], "s3_key": s3_key},
        )
        logger.info(
            "complete_script_upload: created script_id=%s user_id=%s s3_key=%s",
            script.pk,
            user.pk,
            safe_log(s3_key),
        )
        return script
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in complete_script_upload for user_id=%s", user.id)
        raise


def delete_script(user: User, script_id: int) -> None:
    """Soft-delete a script asset.

    Args:
        user: The authenticated user.
        script_id: ID of the script to delete.

    Raises:
        ScriptUploadError: If script not found or not owned by user.
    """
    _validate_user(user, "delete_script")
    logger.debug("delete_script called for user_id=%s script_id=%s", user.id, script_id)
    try:
        try:
            script = ScriptAsset.objects.get(pk=script_id, user=user)
        except ScriptAsset.DoesNotExist:
            logger.warning("delete_script: not found script_id=%s user_id=%s", script_id, user.pk)
            raise ScriptUploadError("Script not found or you don't have access") from None
        _check_result_type(script, ScriptAsset, "delete_script")

        script.deleted_at = timezone.now()
        script.save(update_fields=["deleted_at"])
        audit_log(
            entity_type=AuditLog.EntityType.SCRIPT,
            entity_id=script_id,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={"name": script.name},
        )
        logger.info("delete_script: soft-deleted script_id=%s user_id=%s", script_id, user.pk)
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in delete_script for user_id=%s", user.id)
        raise


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
    _validate_user(user, "list_experiments")
    logger.debug("list_experiments called for user_id=%s", user.id)
    try:
        from django.db.models import Count, Q

        return (
            Experiment.objects.filter(user=user)
            .annotate(
                completed_runs=Count("runs", filter=Q(runs__status=RunStatus.COMPLETED.value)),
                total_run_count=Count("runs"),
            )
            .order_by("-created_at")
        )
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in list_experiments for user_id=%s", user.id)
        raise


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
    _validate_user(user, "get_experiment")
    logger.debug("get_experiment called for user_id=%s experiment_id=%s", user.id, experiment_id)
    try:
        try:
            experiment = Experiment.objects.prefetch_related("runs__artifacts", "scripts__script").get(
                pk=experiment_id, user=user
            )
        except Experiment.DoesNotExist:
            logger.warning("get_experiment: not found experiment_id=%s user_id=%s", experiment_id, user.pk)
            raise ExperimentError("Experiment not found or you don't have access") from None
        _check_result_type(experiment, Experiment, "get_experiment")
        return experiment
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in get_experiment for user_id=%s", user.id)
        raise


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
    _validate_user(user, "create_experiment")
    logger.debug("create_experiment called for user_id=%s scenario=%s", user.id, data.scenario_id)
    try:
        # Validate scenario exists and user has access
        try:
            check_scenario_access(data.scenario_id, user)
            scenario = load_scenario_template(data.scenario_id)
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
                agent = AgentConfig.objects.get(pk=data.agent_id, user=user)
            except AgentConfig.DoesNotExist:
                raise ExperimentValidationError(f"Agent not found: {data.agent_id}") from None
            _check_result_type(agent, AgentConfig, "create_experiment")

        with transaction.atomic():
            experiment = Experiment(
                user=user,
                name=data.name,
                description=data.description,
                scenario_id=data.scenario_id,
                agent=agent,
                total_runs=data.total_runs,
                max_parallel_runs=data.max_parallel_runs,
            )
            try:
                experiment.full_clean()
            except DjangoValidationError as e:
                raise ExperimentValidationError(f"Model validation failed: {e}") from e
            experiment.save()

            for script_input in data.scripts:
                es = ExperimentScript(
                    experiment=experiment,
                    instance_name=script_input.instance_name,
                    script_type=script_input.script_type.value,
                    script_id=script_input.script_id,
                    claude_prompt=script_input.claude_prompt or "",
                    execution_order=script_input.execution_order,
                )
                try:
                    es.full_clean()
                except DjangoValidationError as e:
                    raise ExperimentValidationError(f"Script validation failed: {e}") from e
                es.save()

        audit_log(
            entity_type=AuditLog.EntityType.EXPERIMENT,
            entity_id=experiment.pk,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"name": data.name, "scenario_id": data.scenario_id, "total_runs": data.total_runs},
        )
        logger.info(
            "create_experiment: created experiment_id=%s user_id=%s scenario=%s runs=%d",
            experiment.pk,
            user.pk,
            data.scenario_id,
            data.total_runs,
        )
        return experiment
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in create_experiment for user_id=%s", user.id)
        raise


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
    _validate_user(user, "start_experiment")
    logger.debug("start_experiment called for user_id=%s experiment_id=%s", user.id, experiment_id)
    try:
        with transaction.atomic():
            try:
                experiment = Experiment.objects.select_for_update().get(pk=experiment_id, user=user)
            except Experiment.DoesNotExist:
                raise ExperimentError("Experiment not found or you don't have access") from None
            _check_result_type(experiment, Experiment, "start_experiment")

            if experiment.status != ExperimentStatus.DRAFT.value:
                raise ExperimentStateError(
                    f"Experiment must be in draft state to start (currently {experiment.status})"
                )

            # Create run records
            runs = [ExperimentRun(experiment=experiment, run_number=i) for i in range(1, experiment.total_runs + 1)]
            try:
                ExperimentRun.objects.bulk_create(runs)
            except IntegrityError:
                logger.warning(
                    "start_experiment: duplicate run numbers for experiment_id=%s (concurrent start?)",
                    experiment_id,
                )
                raise ExperimentStateError("Experiment is already being started") from None

            # Transition to queued
            experiment.transition_to(ExperimentStatus.QUEUED)

        # Publish event to trigger orchestration (outside transaction)
        try:
            publish_experiment_event(
                event_type="experiment.start",
                payload={"experiment_id": experiment.pk},
            )
        except Exception as e:
            logger.error(
                "start_experiment: failed to publish start event for experiment_id=%s: %s",
                experiment_id,
                e,
            )
            # Best-effort: don't fail the start operation if event publishing fails
            # The orchestrator can be manually triggered if needed

        audit_log(
            entity_type=AuditLog.EntityType.EXPERIMENT,
            entity_id=experiment.pk,
            action=AuditLog.Action.PROVISION,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"total_runs": experiment.total_runs, "max_parallel_runs": experiment.max_parallel_runs},
        )
        logger.info(
            "start_experiment: queued experiment_id=%s user_id=%s total_runs=%d",
            experiment_id,
            user.pk,
            experiment.total_runs,
        )
        return experiment
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in start_experiment for user_id=%s", user.id)
        raise


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
    _validate_user(user, "cancel_experiment")
    logger.debug("cancel_experiment called for user_id=%s experiment_id=%s", user.id, experiment_id)
    try:
        try:
            experiment = Experiment.objects.get(pk=experiment_id, user=user)
        except Experiment.DoesNotExist:
            raise ExperimentError("Experiment not found or you don't have access") from None
        _check_result_type(experiment, Experiment, "cancel_experiment")

        if experiment.status not in {ExperimentStatus.QUEUED.value, ExperimentStatus.RUNNING.value}:
            raise ExperimentStateError(f"Cannot cancel experiment in {experiment.status} state")

        experiment.transition_to(ExperimentStatus.CANCELLED)
        audit_log(
            entity_type=AuditLog.EntityType.EXPERIMENT,
            entity_id=experiment.pk,
            action=AuditLog.Action.CANCEL,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
        )
        logger.info("cancel_experiment: cancelled experiment_id=%s user_id=%s", experiment_id, user.pk)
        return experiment
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in cancel_experiment for user_id=%s", user.id)
        raise


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
    _validate_user(user, "get_artifact_download_url")
    logger.debug(
        "get_artifact_download_url called for user_id=%s experiment_id=%s artifact_id=%s",
        user.id,
        experiment_id,
        artifact_id,
    )
    try:
        try:
            artifact = RunArtifact.objects.select_related("run__experiment").get(
                pk=artifact_id,
                run__experiment_id=experiment_id,
                run__experiment__user=user,
            )
        except RunArtifact.DoesNotExist:
            raise ArtifactError("Artifact not found or you don't have access") from None
        _check_result_type(artifact, RunArtifact, "get_artifact_download_url")

        try:
            url = generate_presigned_download_url(artifact.s3_key)
        except S3Error as e:
            logger.error("get_artifact_download_url: failed artifact_id=%s: %s", artifact_id, e)
            raise ArtifactError(f"Failed to generate download URL: {e}") from e

        logger.info("get_artifact_download_url: artifact_id=%s user_id=%s", artifact_id, user.pk)
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
    logger.debug("get_bundle_download_url called for user_id=%s experiment_id=%s", user.id, experiment_id)
    try:
        try:
            bundle = ExperimentArtifact.objects.select_related("experiment").get(
                experiment_id=experiment_id,
                experiment__user=user,
            )
        except ExperimentArtifact.DoesNotExist:
            raise ArtifactError("Experiment bundle not found or you don't have access") from None
        _check_result_type(bundle, ExperimentArtifact, "get_bundle_download_url")

        try:
            url = generate_presigned_download_url(bundle.s3_key)
        except S3Error as e:
            logger.error("get_bundle_download_url: failed experiment_id=%s: %s", experiment_id, e)
            raise ArtifactError(f"Failed to generate download URL: {e}") from e

        logger.info("get_bundle_download_url: experiment_id=%s user_id=%s", experiment_id, user.pk)
        return url
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in get_bundle_download_url for user_id=%s", user.id)
        raise


# =============================================================================
# Scenario helpers
# =============================================================================


def get_scenario_instances(scenario_id: str, user: User | None = None) -> list[dict]:
    """Get instance list for a scenario template.

    Args:
        scenario_id: Scenario template ID.
        user: Optional requesting user. If provided, access is checked.

    Returns:
        List of dicts with instance name and role.

    Raises:
        ExperimentValidationError: If scenario not found or access denied.
    """
    logger.debug("get_scenario_instances called for scenario_id=%s", scenario_id)
    if user is not None:
        _validate_user(user, "get_scenario_instances")
    try:
        try:
            if user is not None:
                check_scenario_access(scenario_id, user)
            scenario = load_scenario_template(scenario_id)
        except ValueError as e:
            raise ExperimentValidationError(f"Invalid scenario: {e}") from e

        return [{"name": inst.name, "role": inst.role, "os_type": inst.os_type} for inst in scenario.instances]
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in get_scenario_instances for scenario_id=%s", safe_log(scenario_id))
        raise
