"""Experiment lifecycle service entrypoints.

Names that tests mock through ``cms.experiments.services.<name>``
(``transaction``, ``_check_result_type``, ``audit_log``, model classes)
are looked up against the package at call time so mocks apply across the
package split.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError

from cms.experiments import services as _pkg
from cms.experiments.exceptions import (
    ExperimentError,
    ExperimentStateError,
    ExperimentValidationError,
)
from cms.experiments.schemas import (
    ExperimentCreateInput,
    ExperimentStatus,
    RunStatus,
    ScriptAssignmentInput,
)
from risk_register.models import AuditLog
from shared.log_sanitize import safe_log_value

from ._common import _validate_user

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet

    from cms.experiments.models import Experiment
    from cms.models import AgentConfig
    from cms.scenarios.schema import ScenarioTemplate

logger = logging.getLogger(__name__)


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
            _pkg.Experiment.objects.filter(user=user)
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
            experiment = _pkg.Experiment.objects.prefetch_related("runs__artifacts", "scripts__script").get(
                pk=experiment_id, user=user
            )
        except _pkg.Experiment.DoesNotExist:
            logger.warning("get_experiment: not found experiment_id=%s user_id=%s", experiment_id, user.pk)
            raise ExperimentError("Experiment not found or you don't have access") from None
        _pkg._check_result_type(experiment, _pkg.Experiment, "get_experiment")
        return experiment
    except (TypeError, ValueError, ExperimentError):
        raise
    except Exception:
        logger.exception("Error in get_experiment for user_id=%s", user.id)
        raise


def _resolve_experiment_scenario(scenario_id: str, user: User) -> ScenarioTemplate:
    """Verify access and load the scenario template; raise ExperimentValidationError on either failure."""
    try:
        _pkg.check_scenario_access(scenario_id, user)
        return _pkg.load_scenario_template(scenario_id)
    except ValueError as e:
        logger.warning("create_experiment: invalid scenario_id=%s: %s", safe_log_value(scenario_id), safe_log_value(e))
        raise ExperimentValidationError(f"Invalid scenario: {e}") from e


def _validate_script_assignments(
    scripts: list[ScriptAssignmentInput],
    scenario: ScenarioTemplate,
    user: User,
    scenario_id: str,
) -> None:
    """Reject assignments that don't match an existing instance or aren't owned scripts."""
    instance_names = {inst.name for inst in scenario.instances}
    for script_input in scripts:
        if script_input.instance_name not in instance_names:
            raise ExperimentValidationError(
                f"Instance '{script_input.instance_name}' not found in scenario '{scenario_id}'"
            )
    script_ids = [s.script_id for s in scripts if s.script_id]
    if not script_ids:
        return
    existing_scripts = set(_pkg.ScriptAsset.objects.filter(pk__in=script_ids, user=user).values_list("pk", flat=True))
    missing = set(script_ids) - existing_scripts
    if missing:
        raise ExperimentValidationError(f"Script(s) not found: {missing}")


def _resolve_experiment_agent(agent_id: int | None, user: User) -> AgentConfig | None:
    """Return the user's agent or None; raise ExperimentValidationError if the id is unknown."""
    if not agent_id:
        return None
    from cms.models import AgentConfig

    try:
        agent = AgentConfig.objects.get(pk=agent_id, user=user)
    except AgentConfig.DoesNotExist:
        raise ExperimentValidationError(f"Agent not found: {agent_id}") from None
    _pkg._check_result_type(agent, AgentConfig, "create_experiment")
    return agent


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
    logger.debug("create_experiment called for user_id=%s scenario=%s", user.id, safe_log_value(data.scenario_id))
    try:
        scenario = _resolve_experiment_scenario(data.scenario_id, user)
        _validate_script_assignments(list(data.scripts), scenario, user, data.scenario_id)
        agent = _resolve_experiment_agent(data.agent_id, user)

        with _pkg.transaction.atomic():
            experiment = _pkg.Experiment(
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
                es = _pkg.ExperimentScript(
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

        _pkg.audit_log(
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
            safe_log_value(data.scenario_id),
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
        with _pkg.transaction.atomic():
            try:
                experiment = _pkg.Experiment.objects.select_for_update().get(pk=experiment_id, user=user)
            except _pkg.Experiment.DoesNotExist:
                raise ExperimentError("Experiment not found or you don't have access") from None
            _pkg._check_result_type(experiment, _pkg.Experiment, "start_experiment")

            if experiment.status != ExperimentStatus.DRAFT.value:
                raise ExperimentStateError(
                    f"Experiment must be in draft state to start (currently {experiment.status})"
                )

            # Create run records
            runs = [
                _pkg.ExperimentRun(experiment=experiment, run_number=i) for i in range(1, experiment.total_runs + 1)
            ]
            try:
                _pkg.ExperimentRun.objects.bulk_create(runs)
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
            _pkg.publish_experiment_event(
                event_type="experiment.start",
                payload={"experiment_id": experiment.pk},
            )
        except Exception:
            # Best-effort: don't fail the start operation if event publishing fails.
            # The orchestrator can be manually triggered if needed.
            logger.exception(
                "start_experiment: failed to publish start event for experiment_id=%s",
                experiment_id,
            )

        _pkg.audit_log(
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
            experiment = _pkg.Experiment.objects.get(pk=experiment_id, user=user)
        except _pkg.Experiment.DoesNotExist:
            raise ExperimentError("Experiment not found or you don't have access") from None
        _pkg._check_result_type(experiment, _pkg.Experiment, "cancel_experiment")

        if experiment.status not in {ExperimentStatus.QUEUED.value, ExperimentStatus.RUNNING.value}:
            raise ExperimentStateError(f"Cannot cancel experiment in {experiment.status} state")

        experiment.transition_to(ExperimentStatus.CANCELLED)
        _pkg.audit_log(
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
