"""Inventory of backend-owned feature artifacts acquired by platform recipes."""

from __future__ import annotations

from uuid import uuid4

from django.db import models
from django.db.models import Q


class AcquiredFeatureArtifact(models.Model):
    """One feature artifact Shifter acquired from upstream (ADR-034-R11, R12).

    Records where the bytes live, never the bytes: they are stored in the
    provider-neutral object storage under the content-addressed delivery key, so
    the existing delivery binding and provisioner readback consume them
    unchanged. One row exists per source name, resolved version, and guest
    platform; it is reused by every range that declares that feature.

    ``attempt_id`` fences single-flight acquisition: only the attempt that holds
    the current id may complete or fail the row, so a stale or duplicate Job can
    never overwrite a newer attempt.
    """

    class State(models.TextChoices):
        """Acquisition lifecycle; ``failed`` is never a permanent cache."""

        ACQUIRING = "acquiring", "Acquiring"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source_name = models.CharField(max_length=128)
    resolved_version = models.CharField(max_length=128)
    platform = models.CharField(max_length=64)
    recipe_id = models.CharField(max_length=128)
    payload_kind = models.CharField(max_length=16)
    install_policy = models.CharField(max_length=16)

    state = models.CharField(max_length=16, choices=State.choices, default=State.ACQUIRING)
    attempt_id = models.UUIDField(null=True, blank=True)
    attempt_started_at = models.DateTimeField(null=True, blank=True)
    attempt_expires_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=256, blank=True, default="")
    retry_not_before = models.DateTimeField(null=True, blank=True)

    storage_key = models.CharField(max_length=512, blank=True, default="")
    sha256 = models.CharField(max_length=64, blank=True, default="")
    byte_count = models.BigIntegerField(null=True, blank=True)
    upstream_ref = models.CharField(max_length=512, blank=True, default="")
    upstream_integrity = models.CharField(max_length=128, blank=True, default="")
    acquired_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """One row per artifact identity; a ready row always names its stored object."""

        constraints = [
            models.UniqueConstraint(
                fields=["source_name", "resolved_version", "platform"],
                name="engine_feature_artifact_identity_unique",
            ),
            models.CheckConstraint(
                condition=~Q(state="ready")
                | (~Q(storage_key="") & ~Q(sha256="") & Q(byte_count__gt=0) & Q(acquired_at__isnull=False)),
                name="engine_feature_artifact_ready_has_identity",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_name}@{self.resolved_version} ({self.platform}): {self.state}"
