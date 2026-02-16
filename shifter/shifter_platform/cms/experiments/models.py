"""Experiment manager models.

Models for managing experiment configurations, runs, scripts, and artifacts.
"""

from __future__ import annotations

import logging
from typing import ClassVar
from uuid import uuid4

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from cms.experiments.schemas import (
    EXPERIMENT_TRANSITIONS,
    RUN_TRANSITIONS,
    ArtifactType,
    ExperimentStatus,
    RunStatus,
    ScriptType,
)
from cms.models import FileAsset

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ScriptAsset
# ---------------------------------------------------------------------------


class ScriptAsset(FileAsset):
    """User-uploaded Python script stored in S3.

    Inherits from FileAsset (→ Asset):
      - name, created_at, deleted_at, is_deleted (Asset)
      - s3_key, original_filename, file_size_bytes, sha256_hash, file_size_mb (FileAsset)
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="experiment_scripts",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Script Asset"
        verbose_name_plural = "Script Assets"

    def __str__(self) -> str:
        return f"ScriptAsset(id={self.pk}, name={self.name}, file={self.original_filename})"


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------


class Experiment(models.Model):
    """Top-level experiment configuration."""

    STATUS_CHOICES: ClassVar = [(s.value, s.name.title()) for s in ExperimentStatus]

    uuid = models.UUIDField(unique=True, default=uuid4, editable=False, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="experiments",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    scenario_id = models.CharField(max_length=100, help_text="Scenario template ID")
    agent = models.ForeignKey(
        "cms.AgentConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="experiments",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=ExperimentStatus.DRAFT.value,
        db_index=True,
    )
    total_runs = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    max_parallel_runs = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Experiment"
        verbose_name_plural = "Experiments"

    def __str__(self) -> str:
        return f"Experiment(id={self.pk}, name={self.name}, status={self.status})"

    def transition_to(self, new_status: ExperimentStatus) -> None:
        """Transition experiment to a new status with validation.

        Args:
            new_status: Target status.

        Raises:
            ValueError: If the transition is not allowed.
        """
        current = ExperimentStatus(self.status)
        allowed = EXPERIMENT_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            msg = f"Cannot transition experiment from {current.value} to {new_status.value}"
            logger.error("Experiment %s: %s", self.pk, msg)
            raise ValueError(msg)

        old_status = self.status
        self.status = new_status.value

        if new_status == ExperimentStatus.RUNNING and not self.started_at:
            self.started_at = timezone.now()
        if new_status in {ExperimentStatus.COMPLETED, ExperimentStatus.CANCELLED, ExperimentStatus.FAILED}:
            self.completed_at = timezone.now()

        self.save(update_fields=["status", "updated_at", "started_at", "completed_at"])
        logger.info(
            "Experiment %s transitioned: %s -> %s",
            self.pk,
            old_status,
            new_status.value,
        )

    def clean(self) -> None:
        """Validate model constraints."""
        from django.core.exceptions import ValidationError

        if self.max_parallel_runs > self.total_runs:
            raise ValidationError("max_parallel_runs cannot exceed total_runs")


# ---------------------------------------------------------------------------
# ExperimentScript
# ---------------------------------------------------------------------------


class ExperimentScript(models.Model):
    """Binds a script (or Claude prompt) to a specific instance in an experiment."""

    SCRIPT_TYPE_CHOICES: ClassVar = [(s.value, s.name.title()) for s in ScriptType]

    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="scripts",
    )
    instance_name = models.CharField(max_length=100, help_text="Instance name from scenario template")
    script_type = models.CharField(max_length=20, choices=SCRIPT_TYPE_CHOICES)
    script = models.ForeignKey(
        ScriptAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="experiment_assignments",
    )
    claude_prompt = models.TextField(blank=True, default="")
    execution_order = models.PositiveIntegerField(
        default=0,
        help_text="Lower = earlier. Victims get 0, attacker gets 100.",
    )

    class Meta:
        ordering = ["execution_order", "instance_name"]
        verbose_name = "Experiment Script"
        verbose_name_plural = "Experiment Scripts"
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "instance_name"],
                name="unique_experiment_instance_script",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.instance_name} ({self.script_type})"

    def clean(self) -> None:
        """Validate script type constraints."""
        from django.core.exceptions import ValidationError

        if self.script_type == ScriptType.PYTHON.value and not self.script_id:
            raise ValidationError("Python script type requires a script asset")
        if self.script_type == ScriptType.CLAUDE_CODE.value and not self.claude_prompt:
            raise ValidationError("Claude Code script type requires a prompt")


# ---------------------------------------------------------------------------
# ExperimentRun
# ---------------------------------------------------------------------------


class ExperimentRun(models.Model):
    """A single execution of an experiment's scenario."""

    STATUS_CHOICES: ClassVar = [(s.value, s.name.replace("_", " ").title()) for s in RunStatus]

    uuid = models.UUIDField(unique=True, default=uuid4, editable=False, db_index=True)
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    run_number = models.PositiveIntegerField(help_text="1-based run index")
    request_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Links to CMS/Engine Request",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=RunStatus.PENDING.value,
        db_index=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(null=True, blank=True, help_text="Runtime data: IPs, timing, etc.")

    class Meta:
        ordering = ["run_number"]
        verbose_name = "Experiment Run"
        verbose_name_plural = "Experiment Runs"
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "run_number"],
                name="unique_experiment_run_number",
            ),
        ]

    def __str__(self) -> str:
        return f"Run(id={self.pk}, experiment={self.experiment_id}, num={self.run_number}, status={self.status})"

    def transition_to(self, new_status: RunStatus) -> None:
        """Transition run to a new status with validation.

        Args:
            new_status: Target status.

        Raises:
            ValueError: If the transition is not allowed.
        """
        current = RunStatus(self.status)
        allowed = RUN_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            msg = f"Cannot transition run from {current.value} to {new_status.value}"
            logger.error(
                "ExperimentRun %s (experiment=%s): %s",
                self.pk,
                self.experiment_id,
                msg,
            )
            raise ValueError(msg)

        old_status = self.status
        self.status = new_status.value

        if new_status == RunStatus.PROVISIONING and not self.started_at:
            self.started_at = timezone.now()
        if new_status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            self.completed_at = timezone.now()

        self.save(update_fields=["status", "started_at", "completed_at"])
        logger.info(
            "ExperimentRun %s (experiment=%s): %s -> %s",
            self.pk,
            self.experiment_id,
            old_status,
            new_status.value,
        )


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class RunArtifact(models.Model):
    """Collected output from a specific instance within a run."""

    ARTIFACT_TYPE_CHOICES: ClassVar = [(a.value, a.name.replace("_", " ").title()) for a in ArtifactType]

    run = models.ForeignKey(
        ExperimentRun,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    instance_name = models.CharField(max_length=100)
    artifact_type = models.CharField(max_length=30, choices=ARTIFACT_TYPE_CHOICES)
    s3_key = models.CharField(max_length=500)
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["instance_name", "artifact_type"]
        verbose_name = "Run Artifact"
        verbose_name_plural = "Run Artifacts"

    def __str__(self) -> str:
        return f"{self.instance_name}/{self.artifact_type}"


class ExperimentArtifact(models.Model):
    """Bundled zip of all run artifacts for a completed experiment."""

    experiment = models.OneToOneField(
        Experiment,
        on_delete=models.CASCADE,
        related_name="bundle",
    )
    s3_key = models.CharField(max_length=500)
    file_size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Experiment Artifact"
        verbose_name_plural = "Experiment Artifacts"

    def __str__(self) -> str:
        return f"Bundle for {self.experiment.name}"
