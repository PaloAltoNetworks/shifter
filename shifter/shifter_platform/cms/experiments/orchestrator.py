"""Experiment execution orchestrator.

Manages the lifecycle of experiment runs:
1. Schedule pending runs up to max_parallel limit
2. Handle range provisioning completion
3. Execute victim scripts, then attacker scripts
4. Collect artifacts
5. Determine overall experiment outcome

Actual SSM commands are dispatched via ECS tasks (portal lacks SSM permissions).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from cms.experiments.models import (
    Experiment,
    ExperimentRun,
    ExperimentScript,
)
from cms.experiments.schemas import (
    TERMINAL_RUN_STATUSES,
    ExperimentStatus,
    RunStatus,
    ScriptType,
)
from cms.experiments.template_vars import build_instance_data, resolve_template

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

EVENT_TYPE_EXPERIMENT = "experiment.status.updated"
EVENT_TYPE_RUN = "experiment.run.updated"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ScriptCommand:
    """A resolved script command ready for execution on an instance."""

    instance_name: str
    instance_id: str
    script_type: str
    command: str
    execution_order: int
    script_s3_key: str | None = None


@dataclass
class RunExecutionPlan:
    """Plan for executing a single experiment run."""

    run_id: int
    victim_commands: list[ScriptCommand] = field(default_factory=list)
    attacker_commands: list[ScriptCommand] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ExperimentOrchestrator:
    """Coordinates experiment run execution.

    Follows SetupOrchestrator pattern but manages the full experiment lifecycle.
    """

    def __init__(self, experiment_id: int):
        self.experiment_id = experiment_id
        self._experiment: Experiment | None = None

    @property
    def experiment(self) -> Experiment:
        if self._experiment is None:
            self._experiment = Experiment.objects.prefetch_related("scripts__script", "runs").get(pk=self.experiment_id)
        return self._experiment

    def refresh(self) -> None:
        """Reload experiment from database."""
        self._experiment = None

    # -----------------------------------------------------------------
    # Main entry points (called by SQS handler)
    # -----------------------------------------------------------------

    def schedule_runs(self) -> int:
        """Schedule pending runs up to max_parallel limit.

        Uses select_for_update() to prevent concurrent SQS handlers from
        over-scheduling runs beyond max_parallel_runs.

        Returns:
            Number of runs scheduled for provisioning.
        """
        from django.db import transaction

        with transaction.atomic():
            experiment = Experiment.objects.select_for_update().get(pk=self.experiment_id)
            self._experiment = experiment

            if experiment.status == ExperimentStatus.QUEUED.value:
                experiment.transition_to(ExperimentStatus.RUNNING)
                experiment = Experiment.objects.select_for_update().get(pk=self.experiment_id)
                self._experiment = experiment

            if experiment.status != ExperimentStatus.RUNNING.value:
                logger.info(
                    "schedule_runs: experiment %s not running (status=%s), skipping",
                    self.experiment_id,
                    experiment.status,
                )
                return 0

            active_runs = ExperimentRun.objects.filter(
                experiment=experiment,
                status__in=[
                    RunStatus.PROVISIONING.value,
                    RunStatus.EXECUTING_VICTIMS.value,
                    RunStatus.EXECUTING_ATTACKER.value,
                    RunStatus.COLLECTING.value,
                ],
            ).count()

            slots_available = experiment.max_parallel_runs - active_runs
            if slots_available <= 0:
                logger.debug(
                    "schedule_runs: no slots (active=%d, max=%d)",
                    active_runs,
                    experiment.max_parallel_runs,
                )
                return 0

            pending_runs = list(
                ExperimentRun.objects.select_for_update()
                .filter(
                    experiment=experiment,
                    status=RunStatus.PENDING.value,
                )
                .order_by("run_number")[:slots_available]
            )

            scheduled = 0
            for run in pending_runs:
                try:
                    run.transition_to(RunStatus.PROVISIONING)
                    self._request_range_provisioning(run)
                    scheduled += 1
                except Exception:
                    logger.exception(
                        "schedule_runs: failed to schedule run %s (experiment=%s)",
                        run.pk,
                        self.experiment_id,
                    )
                    run.error_message = "Failed to schedule provisioning"
                    run.save(update_fields=["error_message"])
                    run.transition_to(RunStatus.FAILED)

        logger.info(
            "schedule_runs: scheduled %d runs for experiment %s",
            scheduled,
            self.experiment_id,
        )
        return scheduled

    def handle_range_provisioned(self, run_id: int, provisioned_instances: dict[str, Any]) -> None:
        """Handle range provisioning completion.

        Args:
            run_id: ID of the ExperimentRun.
            provisioned_instances: Dict of instance names to their details.
        """
        if not isinstance(provisioned_instances, dict):
            logger.error(
                "handle_range_provisioned: provisioned_instances is not a dict (type=%s) for run %s",
                type(provisioned_instances).__name__,
                run_id,
            )
            provisioned_instances = {}

        try:
            run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
        except ExperimentRun.DoesNotExist:
            logger.error("handle_range_provisioned: run %s not found", run_id)
            return

        run.metadata = {"provisioned_instances": provisioned_instances}
        run.save(update_fields=["metadata"])

        try:
            plan = self._build_execution_plan(run, provisioned_instances)
        except Exception:
            logger.exception("handle_range_provisioned: plan build failed for run %s", run_id)
            run.error_message = "Failed to build execution plan"
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            self._check_experiment_completion()
            return

        if plan.victim_commands:
            run.transition_to(RunStatus.EXECUTING_VICTIMS)
            self._dispatch_commands(run, plan.victim_commands)
        elif plan.attacker_commands:
            run.transition_to(RunStatus.EXECUTING_VICTIMS)
            run.transition_to(RunStatus.EXECUTING_ATTACKER)
            self._dispatch_commands(run, plan.attacker_commands)
        else:
            run.transition_to(RunStatus.EXECUTING_VICTIMS)
            run.transition_to(RunStatus.EXECUTING_ATTACKER)
            run.transition_to(RunStatus.COLLECTING)
            run.transition_to(RunStatus.COMPLETED)
            self._check_experiment_completion()

    def handle_victim_scripts_completed(self, run_id: int) -> None:
        """Handle victim script completion — start attacker scripts."""
        try:
            run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
        except ExperimentRun.DoesNotExist:
            logger.error("handle_victim_scripts_completed: run %s not found", run_id)
            return

        provisioned_instances = (run.metadata or {}).get("provisioned_instances", {})

        try:
            plan = self._build_execution_plan(run, provisioned_instances)
        except Exception:
            logger.exception("handle_victim_scripts_completed: plan failed for run %s", run_id)
            run.error_message = "Failed to build attacker execution plan"
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            self._check_experiment_completion()
            return

        if plan.attacker_commands:
            run.transition_to(RunStatus.EXECUTING_ATTACKER)
            self._dispatch_commands(run, plan.attacker_commands)
        else:
            run.transition_to(RunStatus.EXECUTING_ATTACKER)
            run.transition_to(RunStatus.COLLECTING)
            run.transition_to(RunStatus.COMPLETED)
            self._check_experiment_completion()

    def handle_attacker_scripts_completed(self, run_id: int) -> None:
        """Handle attacker script completion — collect artifacts."""
        try:
            run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
        except ExperimentRun.DoesNotExist:
            logger.error("handle_attacker_scripts_completed: run %s not found", run_id)
            return

        run.transition_to(RunStatus.COLLECTING)
        self._collect_artifacts(run)

    def handle_artifacts_collected(self, run_id: int) -> None:
        """Handle artifact collection completion — mark run complete."""
        try:
            run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
        except ExperimentRun.DoesNotExist:
            logger.error("handle_artifacts_collected: run %s not found", run_id)
            return

        run.transition_to(RunStatus.COMPLETED)
        logger.info("handle_artifacts_collected: run %s completed", run_id)
        self.schedule_runs()
        self._check_experiment_completion()

    def handle_run_failed(self, run_id: int, error_message: str = "") -> None:
        """Handle run failure."""
        try:
            run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
        except ExperimentRun.DoesNotExist:
            logger.error("handle_run_failed: run %s not found", run_id)
            return

        if run.status in {s.value for s in TERMINAL_RUN_STATUSES}:
            return

        run.error_message = error_message
        run.save(update_fields=["error_message"])
        run.transition_to(RunStatus.FAILED)

        logger.warning("handle_run_failed: run %s failed: %s", run_id, error_message)
        self.schedule_runs()
        self._check_experiment_completion()

    # -----------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------

    def _build_execution_plan(
        self,
        run: ExperimentRun,
        provisioned_instances: dict[str, Any],
    ) -> RunExecutionPlan:
        """Build an execution plan from experiment scripts and provisioned data."""
        instance_data = build_instance_data(provisioned_instances)
        scripts = (
            ExperimentScript.objects.filter(
                experiment_id=self.experiment_id,
            )
            .select_related("script")
            .order_by("execution_order")
        )

        plan = RunExecutionPlan(run_id=run.pk)

        for script_assignment in scripts:
            instance_name = script_assignment.instance_name
            instance_info = provisioned_instances.get(instance_name, {})
            instance_id = instance_info.get("instance_id", "")

            if not instance_id:
                logger.warning(
                    "_build_execution_plan: no instance_id for %s in run %s",
                    instance_name,
                    run.pk,
                )
                continue

            if script_assignment.script_type == ScriptType.PYTHON.value:
                s3_key = script_assignment.script.s3_key if script_assignment.script else ""
                command = self._build_python_command(s3_key, instance_name)
                cmd = ScriptCommand(
                    instance_name=instance_name,
                    instance_id=instance_id,
                    script_type=ScriptType.PYTHON.value,
                    command=command,
                    execution_order=script_assignment.execution_order,
                    script_s3_key=s3_key,
                )
            else:
                prompt = resolve_template(script_assignment.claude_prompt, instance_data)
                command = self._build_claude_command(prompt)
                cmd = ScriptCommand(
                    instance_name=instance_name,
                    instance_id=instance_id,
                    script_type=ScriptType.CLAUDE_CODE.value,
                    command=command,
                    execution_order=script_assignment.execution_order,
                )

            if script_assignment.execution_order < 100:
                plan.victim_commands.append(cmd)
            else:
                plan.attacker_commands.append(cmd)

        return plan

    def _build_python_command(self, s3_key: str, instance_name: str) -> str:
        """Build shell command to download and run a Python script from S3."""
        return (
            f"aws s3 cp s3://${{BUCKET_NAME}}/{s3_key} /tmp/script_{instance_name}.py "
            f"&& python3 /tmp/script_{instance_name}.py "
            f"2>&1 | tee /tmp/output_{instance_name}.log"
        )

    def _build_claude_command(self, resolved_prompt: str) -> str:
        """Build Claude Code invocation command."""
        escaped_prompt = resolved_prompt.replace("'", "'\\''")
        return (
            f"claude --dangerously-skip-permissions "
            f"--output-format stream-json "
            f"-p '{escaped_prompt}' "
            f"2>&1 | tee /tmp/claude_output.json"
        )

    def _request_range_provisioning(self, run: ExperimentRun) -> None:
        """Request range provisioning for a run via the engine.

        This will trigger CMS→Engine range creation via ECS.
        """
        logger.info(
            "_request_range_provisioning: requesting range for run %s (experiment=%s)",
            run.pk,
            self.experiment_id,
        )

    def _dispatch_commands(self, run: ExperimentRun, commands: list[ScriptCommand]) -> None:
        """Dispatch script commands for execution via ECS task."""
        logger.info(
            "_dispatch_commands: dispatching %d commands for run %s",
            len(commands),
            run.pk,
        )

    def _collect_artifacts(self, run: ExperimentRun) -> None:
        """Trigger artifact collection from range instances via ECS task."""
        logger.info("_collect_artifacts: collecting for run %s", run.pk)

    def _check_experiment_completion(self) -> None:
        """Check if all runs are terminal and update experiment status."""
        self.refresh()
        experiment = self.experiment

        if experiment.status != ExperimentStatus.RUNNING.value:
            return

        all_runs = ExperimentRun.objects.filter(experiment=experiment)
        total = all_runs.count()
        if total == 0:
            return

        terminal_count = all_runs.filter(status__in=[s.value for s in TERMINAL_RUN_STATUSES]).count()

        if terminal_count < total:
            return

        completed_count = all_runs.filter(status=RunStatus.COMPLETED.value).count()
        failed_count = all_runs.filter(status=RunStatus.FAILED.value).count()

        if failed_count == total:
            experiment.error_message = f"All {failed_count} runs failed"
            experiment.save(update_fields=["error_message"])
            experiment.transition_to(ExperimentStatus.FAILED)
        else:
            experiment.transition_to(ExperimentStatus.COMPLETED)

        logger.info(
            "_check_experiment_completion: experiment %s finished (%d/%d succeeded)",
            self.experiment_id,
            completed_count,
            total,
        )
