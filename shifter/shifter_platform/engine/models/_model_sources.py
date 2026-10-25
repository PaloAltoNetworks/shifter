"""Tenant-owned source metadata; provider secrets live in the cloud secret store."""

from uuid import uuid4

from django.conf import settings
from django.db import models


class ModelSource(models.Model):
    """Mutable publication pointer guarded by compare-and-swap revision checks."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    organization_uuid = models.UUIDField(db_index=True)
    revision = models.PositiveBigIntegerField(default=1)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Enforce publication revision and lifecycle invariants in storage."""

        constraints = [
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="model_source_revision_positive")
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelSourceRevision(models.Model):
    """Immutable intent and exact credential reference with durable write recovery."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source = models.ForeignKey(ModelSource, on_delete=models.PROTECT, related_name="revisions")
    revision = models.PositiveBigIntegerField()
    configuration = models.JSONField()
    credential_version = models.UUIDField(null=True)
    credential_reference = models.CharField(max_length=1024, blank=True)
    state = models.CharField(max_length=16, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True)

    class Meta:
        """Enforce publication revision and lifecycle invariants in storage."""

        constraints = [
            models.UniqueConstraint(fields=["source", "revision"], name="model_source_unique_revision"),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="model_source_version_positive"),
            models.CheckConstraint(
                condition=models.Q(state__in=["pending", "ready", "failed", "retired"]),
                name="model_source_version_state",
            ),
        ]

    def __str__(self) -> str:
        return str(self.pk)


class ModelSourceRegistry(models.Model):
    """Engine-owned mutex for the bounded source registry of one tenant."""

    organization_uuid = models.UUIDField(primary_key=True)

    def __str__(self) -> str:
        return str(self.pk)
