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
from uuid import uuid4

from cyberscript.script_context import (
    ScriptExecutionContext,
    build_ai_execution_policy_payload,
)
from cyberscript.template_vars import build_instance_data
from pydantic import ValidationError

from cms.experiments.ecs import start_experiment_task
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
from engine.services import create_range as engine_create_range
from risk_register.models import AuditLog
from risk_register.services import StateChange, audit_log_system_event

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

    def __init__(self, experiment_id: int) -> None:
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
        logger.debug("handle_range_provisioned called for run %s", run_id)
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
            logger.warning("handle_range_provisioned: run %s not found", run_id)
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
        logger.debug("handle_victim_scripts_completed called for run %s", run_id)
        try:
            try:
                run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
            except ExperimentRun.DoesNotExist:
                logger.warning("handle_victim_scripts_completed: run %s not found", run_id)
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
        except Exception:
            logger.exception("handle_victim_scripts_completed: unexpected error for run %s", run_id)
            self.handle_run_failed(run_id, "Unexpected orchestrator error during victim completion")

    def handle_attacker_scripts_completed(self, run_id: int) -> None:
        """Handle attacker script completion — collect artifacts."""
        logger.debug("handle_attacker_scripts_completed called for run %s", run_id)
        try:
            try:
                run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
            except ExperimentRun.DoesNotExist:
                logger.warning("handle_attacker_scripts_completed: run %s not found", run_id)
                return

            run.transition_to(RunStatus.COLLECTING)
            self._collect_artifacts(run)
        except Exception:
            logger.exception("handle_attacker_scripts_completed: unexpected error for run %s", run_id)
            self.handle_run_failed(run_id, "Unexpected orchestrator error during attacker completion")

    def handle_artifacts_collected(self, run_id: int) -> None:
        """Handle artifact collection completion — mark run complete."""
        logger.debug("handle_artifacts_collected called for run %s", run_id)
        try:
            try:
                run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
            except ExperimentRun.DoesNotExist:
                logger.warning("handle_artifacts_collected: run %s not found", run_id)
                return

            run.transition_to(RunStatus.COMPLETED)
            logger.info("handle_artifacts_collected: run %s completed", run_id)
            self.schedule_runs()
            self._check_experiment_completion()
        except Exception:
            logger.exception("handle_artifacts_collected: unexpected error for run %s", run_id)
            self.handle_run_failed(run_id, "Unexpected orchestrator error during artifact collection")

    def handle_run_failed(self, run_id: int, error_message: str = "") -> None:
        """Handle run failure."""
        logger.debug("handle_run_failed called for run %s error=%s", run_id, error_message)
        try:
            try:
                run = ExperimentRun.objects.get(pk=run_id, experiment_id=self.experiment_id)
            except ExperimentRun.DoesNotExist:
                logger.warning("handle_run_failed: run %s not found", run_id)
                return

            if run.status in {s.value for s in TERMINAL_RUN_STATUSES}:
                return

            run.error_message = error_message
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)

            logger.warning("handle_run_failed: run %s failed: %s", run_id, error_message)
            self.schedule_runs()
            self._check_experiment_completion()
        except Exception:
            logger.exception("handle_run_failed: unexpected error for run %s", run_id)

    # -----------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------

    def _build_execution_plan(
        self,
        run: ExperimentRun,
        provisioned_instances: dict[str, Any],
    ) -> RunExecutionPlan:
        """Build an execution plan from experiment scripts and provisioned data.

        Raises:
            ExecutionPlanError: If required instances are missing from provisioned data,
                or if the configured cloud provider is not AWS (experiment script
                execution lands in SSM RunCommand, which is AWS-only today).
        """
        from cms.experiments.exceptions import ExecutionPlanError

        self._enforce_aws_only_provider(run)

        instance_data = build_instance_data(provisioned_instances)
        scripts = (
            ExperimentScript.objects.filter(
                experiment_id=self.experiment_id,
            )
            .select_related("script")
            .order_by("execution_order")
        )

        plan = RunExecutionPlan(run_id=run.pk)
        missing_instances: list[str] = []

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
                missing_instances.append(instance_name)
                continue

            cmd = self._build_script_command(
                run=run,
                script_assignment=script_assignment,
                instance_name=instance_name,
                instance_info=instance_info,
                instance_id=instance_id,
                instance_data=instance_data,
            )

            if script_assignment.execution_order < 100:
                plan.victim_commands.append(cmd)
            else:
                plan.attacker_commands.append(cmd)

        # Fail fast if instances are missing
        if missing_instances:
            raise ExecutionPlanError(
                f"Cannot build execution plan for run {run.pk}: missing instances {missing_instances}"
            )

        return plan

    @staticmethod
    def _enforce_aws_only_provider(run: ExperimentRun) -> None:
        """Gate non-AWS providers with a clear `ExecutionPlanError` before plan construction.

        `cyberscript.script_context.ScriptExecutionContext` validates EC2 instance
        IDs and renders `aws s3 cp` shell text; today's dispatch path lands in SSM
        RunCommand, which is AWS-only. Surface this explicitly rather than letting
        the validator's `i-…` rejection masquerade as an unsupported-provider error.
        """
        from django.conf import settings

        from cms.experiments.exceptions import ExecutionPlanError

        provider = (getattr(settings, "CLOUD_PROVIDER", None) or "aws").lower()
        if provider != "aws":
            raise ExecutionPlanError(
                f"Cannot build execution plan for run {run.pk}: experiment "
                f"script execution is AWS-only today (CLOUD_PROVIDER={provider!r})."
            )

    def _build_script_command(
        self,
        *,
        run: ExperimentRun,
        script_assignment: ExperimentScript,
        instance_name: str,
        instance_info: dict[str, Any],
        instance_id: str,
        instance_data: dict[str, dict[str, Any]],
    ) -> ScriptCommand:
        """Construct a single `ScriptCommand` from a script assignment.

        Wraps `ScriptExecutionContext` construction and rendering so the loop in
        `_build_execution_plan` stays declarative. Any `pydantic.ValidationError`
        is surfaced as `ExecutionPlanError` with the rejected input value redacted
        from the message — Pydantic's default `str()` includes `input_value=`.
        """
        from cms.experiments.exceptions import ExecutionPlanError

        private_ip = instance_info.get("private_ip") or None

        try:
            if script_assignment.script_type == ScriptType.PYTHON.value:
                return self._build_python_script_command(
                    script_assignment=script_assignment,
                    instance_name=instance_name,
                    instance_id=instance_id,
                    private_ip=private_ip,
                )
            if script_assignment.script_type == ScriptType.CLAUDE_CODE.value:
                return self._build_claude_script_command(
                    script_assignment=script_assignment,
                    instance_name=instance_name,
                    instance_id=instance_id,
                    private_ip=private_ip,
                    instance_data=instance_data,
                )
            raise ExecutionPlanError(
                f"Cannot build execution plan for run {run.pk}: unknown script_type for instance '{instance_name}'"
            )
        except ValidationError as exc:
            summary = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors(include_input=False)
            )
            raise ExecutionPlanError(
                f"Cannot build execution plan for run {run.pk}: script for instance failed validation: {summary}"
            ) from exc

    @staticmethod
    def _build_python_script_command(
        *,
        script_assignment: ExperimentScript,
        instance_name: str,
        instance_id: str,
        private_ip: str | None,
    ) -> ScriptCommand:
        s3_key = script_assignment.script.s3_key if script_assignment.script else ""
        ctx = ScriptExecutionContext.for_python(
            instance_name=instance_name,
            instance_id=instance_id,
            private_ip=private_ip,
            script_s3_key=s3_key,
        )
        return ScriptCommand(
            instance_name=instance_name,
            instance_id=instance_id,
            script_type=ScriptType.PYTHON.value,
            command=ctx.render_command(),
            execution_order=script_assignment.execution_order,
            script_s3_key=s3_key,
        )

    @staticmethod
    def _build_claude_script_command(
        *,
        script_assignment: ExperimentScript,
        instance_name: str,
        instance_id: str,
        private_ip: str | None,
        instance_data: dict[str, dict[str, Any]],
    ) -> ScriptCommand:
        ctx = ScriptExecutionContext.for_claude(
            instance_name=instance_name,
            instance_id=instance_id,
            private_ip=private_ip,
            claude_prompt_template=script_assignment.claude_prompt,
            instance_data=instance_data,
        )
        return ScriptCommand(
            instance_name=instance_name,
            instance_id=instance_id,
            script_type=ScriptType.CLAUDE_CODE.value,
            command=ctx.render_command(),
            execution_order=script_assignment.execution_order,
        )

    def _request_range_provisioning(self, run: ExperimentRun) -> None:
        """Request range provisioning for a run via the engine.

        Follows the same hydrate → RequestSpec → engine pattern as
        cms.services.create_range, adapted for experiment runs:
        - No "active range" guard (experiments provision many ranges)
        - Agent comes from experiment.agent rather than per-request input
        - request_id is stored on ExperimentRun for event correlation

        On failure the run is transitioned to FAILED with an error message
        and the method returns (does not raise).

        Args:
            run: The ExperimentRun to provision a range for. Must already be
                in PROVISIONING status.
        """
        from cms.exceptions import CMSError
        from cms.models import AgentConfig, RangeInstance, Request
        from cms.scenarios.hydrator import hydrate_scenario
        from shared.enums import RequestType
        from shared.schemas import RequestSpec

        experiment = self.experiment
        scenario_id: str = experiment.scenario_id
        user = experiment.user

        logger.info(
            "_request_range_provisioning: run=%d experiment=%d scenario=%s user=%d",
            run.pk,
            self.experiment_id,
            scenario_id,
            user.pk,
        )

        # --- Build agents dict from experiment's agent ---
        agent: AgentConfig | None = experiment.agent
        agents: dict[str, AgentConfig] = {}

        if agent is not None:
            if agent.deleted_at is not None:
                msg = f"Agent '{agent.name}' (id={agent.pk}) has been deleted"
                logger.error(
                    "_request_range_provisioning: %s (run=%d)",
                    msg,
                    run.pk,
                )
                run.error_message = msg
                run.save(update_fields=["error_message"])
                run.transition_to(RunStatus.FAILED)
                return

            os_key = "windows" if agent.os.slug.lower() == "windows" else "linux"
            agents[os_key] = agent

        # --- Hydrate scenario ---
        try:
            range_spec = hydrate_scenario(scenario_id, user.pk, agents)
        except (CMSError, ValueError) as exc:
            msg = f"Scenario hydration failed for '{scenario_id}': {exc}"
            logger.error(
                "_request_range_provisioning: %s (run=%d)",
                msg,
                run.pk,
            )
            run.error_message = msg
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            return

        # --- Create CMS Request record ---
        request_id = uuid4()
        cms_request = Request.objects.create(
            request_id=request_id,
            request_type=RequestType.RANGE.value,
            user=user,
        )

        # --- Store request_id on run for event correlation ---
        run.request_id = request_id
        run.save(update_fields=["request_id"])

        logger.info(
            "_request_range_provisioning: created Request %s for run=%d",
            request_id,
            run.pk,
        )

        # --- Wrap RangeSpec in RequestSpec and call engine ---
        request_spec = RequestSpec(
            request_id=request_id,
            user_id=user.pk,
            items=[range_spec],
        )

        try:
            engine_create_range(request_spec)
        except Exception as exc:
            msg = f"Engine create_range failed: {exc}"
            logger.exception(
                "_request_range_provisioning: %s (run=%d, request_id=%s)",
                msg,
                run.pk,
                request_id,
            )
            run.error_message = msg
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            return

        # --- Create RangeInstance tracking record ---
        RangeInstance.objects.create(
            request=cms_request,
            scenario_id=scenario_id,
            user_id=user.pk,
            agent=agent,
            range_spec=range_spec.model_dump(mode="json"),
        )

        logger.info(
            "_request_range_provisioning: provisioning triggered for run=%d request_id=%s scenario=%s",
            run.pk,
            request_id,
            scenario_id,
        )

    def _dispatch_commands(self, run: ExperimentRun, commands: list[ScriptCommand]) -> None:
        """Dispatch script commands for execution via ECS task.

        Serializes the commands as a JSON payload and starts an ECS Fargate
        task to execute them on the provisioned range instances via SSM.

        On success the ECS task ARN is stored in run.metadata. On failure
        (ECS not configured or API error) the run transitions to FAILED.

        Idempotency: If a task ARN already exists in metadata, logs a warning
        and returns without dispatching to prevent duplicate task submissions
        on retries or duplicate events.

        Args:
            run: The ExperimentRun being executed. Must have request_id set.
            commands: List of resolved ScriptCommand objects to execute.
        """
        from dataclasses import asdict

        # Idempotency check: Don't dispatch if already dispatched
        existing_arn = (run.metadata or {}).get("dispatch_task_arn")
        if existing_arn:
            logger.warning(
                "_dispatch_commands: run %d already has dispatch_task_arn=%s, skipping duplicate dispatch",
                run.pk,
                existing_arn,
            )
            return

        logger.info(
            "_dispatch_commands: dispatching %d commands for run=%d (experiment=%d)",
            len(commands),
            run.pk,
            self.experiment_id,
        )

        payload = {
            "ai_execution_policy": build_ai_execution_policy_payload(),
            "commands": [asdict(cmd) for cmd in commands],
        }

        if run.request_id is None:
            msg = "ExperimentRun has no request_id — cannot dispatch commands"
            logger.error("_dispatch_commands: %s (run=%d)", msg, run.pk)
            run.error_message = msg
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            return

        dispatch_error: str | None = None
        try:
            task_arn = start_experiment_task(
                experiment_id=self.experiment_id,
                run_id=run.pk,
                request_id=run.request_id,
                command="execute",
                payload=payload,
            )
        except Exception as exc:
            dispatch_error = f"Failed to start execution ECS task: {exc}"
            logger.exception("_dispatch_commands: %s (run=%d)", dispatch_error, run.pk)
            task_arn = None

        # Single failure exit covers both the exception and the not-configured
        # (task_arn is None) cases, keeping this method under the return cap (S1142).
        if task_arn is None:
            msg = dispatch_error or "ECS not configured — cannot dispatch experiment commands"
            if dispatch_error is None:
                logger.error("_dispatch_commands: %s (run=%d)", msg, run.pk)
            run.error_message = msg
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            return

        # Store task ARN in metadata for debugging/correlation
        metadata = run.metadata or {}
        metadata["dispatch_task_arn"] = task_arn
        run.metadata = metadata
        run.save(update_fields=["metadata"])

        logger.info(
            "_dispatch_commands: started ECS task=%s for run=%d",
            task_arn,
            run.pk,
        )

    def _collect_artifacts(self, run: ExperimentRun) -> None:
        """Trigger artifact collection from range instances via ECS task.

        Starts an ECS Fargate task that copies output files from range
        instances to S3 and creates RunArtifact/ExperimentArtifact records.

        On success the ECS task ARN is stored in run.metadata. On failure
        the run transitions to FAILED.

        Idempotency: If a collection task ARN already exists in metadata, logs
        a warning and returns without dispatching to prevent duplicate task
        submissions on retries or duplicate events.

        Args:
            run: The ExperimentRun to collect artifacts for.
                Must have request_id set.
        """
        # Idempotency check: Don't collect if already started
        existing_arn = (run.metadata or {}).get("collect_task_arn")
        if existing_arn:
            logger.warning(
                "_collect_artifacts: run %d already has collect_task_arn=%s, skipping duplicate collection",
                run.pk,
                existing_arn,
            )
            return

        logger.info(
            "_collect_artifacts: collecting for run=%d (experiment=%d)",
            run.pk,
            self.experiment_id,
        )

        if run.request_id is None:
            msg = "ExperimentRun has no request_id — cannot collect artifacts"
            logger.error("_collect_artifacts: %s (run=%d)", msg, run.pk)
            run.error_message = msg
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            return

        collect_error: str | None = None
        try:
            task_arn = start_experiment_task(
                experiment_id=self.experiment_id,
                run_id=run.pk,
                request_id=run.request_id,
                command="collect",
            )
        except Exception as exc:
            collect_error = f"Failed to start collection ECS task: {exc}"
            logger.exception("_collect_artifacts: %s (run=%d)", collect_error, run.pk)
            task_arn = None

        # Single failure exit covers both the exception and the not-configured
        # (task_arn is None) cases, keeping this method under the return cap (S1142).
        if task_arn is None:
            msg = collect_error or "ECS not configured — cannot collect experiment artifacts"
            if collect_error is None:
                logger.error("_collect_artifacts: %s (run=%d)", msg, run.pk)
            run.error_message = msg
            run.save(update_fields=["error_message"])
            run.transition_to(RunStatus.FAILED)
            return

        # Store task ARN in metadata for debugging/correlation
        metadata = run.metadata or {}
        metadata["collect_task_arn"] = task_arn
        run.metadata = metadata
        run.save(update_fields=["metadata"])

        logger.info(
            "_collect_artifacts: started ECS task=%s for run=%d",
            task_arn,
            run.pk,
        )

    def _check_experiment_completion(self) -> None:
        """Check if all runs are terminal and update experiment status."""
        try:
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
                audit_log_system_event(
                    entity_type=AuditLog.EntityType.EXPERIMENT,
                    entity_id=self.experiment_id,
                    action=AuditLog.Action.FAILED,
                    source="experiments.orchestrator",
                    context=experiment.error_message or "",
                )
            else:
                experiment.transition_to(ExperimentStatus.COMPLETED)
                audit_log_system_event(
                    entity_type=AuditLog.EntityType.EXPERIMENT,
                    entity_id=self.experiment_id,
                    action=AuditLog.Action.READY,
                    source="experiments.orchestrator",
                    state=StateChange(new={"completed_runs": completed_count, "failed_runs": failed_count}),
                )

            logger.info(
                "_check_experiment_completion: experiment %s finished (%d/%d succeeded)",
                self.experiment_id,
                completed_count,
                total,
            )
        except Exception:
            logger.exception("_check_experiment_completion: unexpected error for experiment %s", self.experiment_id)
