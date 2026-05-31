"""Mission Control persistence models."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class GuacamoleBootstrapRequest(models.Model):
    """Pollable state for asynchronous Guacamole URL bootstrap."""

    class Protocol(models.TextChoices):
        RDP = "rdp", "RDP"
        RANGE_SSH = "range_ssh", "Range SSH"
        NGFW_SSH = "ngfw_ssh", "NGFW SSH"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.PositiveBigIntegerField(db_index=True)
    protocol = models.CharField(max_length=16, choices=Protocol.choices)
    target_id = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    result_url = models.TextField(blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    error_status_code = models.PositiveSmallIntegerField(default=500)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("user_id", "created_at"), name="mc_guac_boot_user_idx"),
            models.Index(fields=("status", "expires_at"), name="mc_guac_boot_state_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.protocol}:{self.target_id}:{self.status}"

    @property
    def is_expired(self) -> bool:
        """Return whether this bootstrap record should no longer be used."""
        return self.expires_at <= timezone.now()
