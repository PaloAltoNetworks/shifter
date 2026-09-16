"""Engine-owned signed-receipt verifier registration records."""

from __future__ import annotations

import uuid

from django.db import models

from shared.receipt_validation import ReceiptKeyMode

_EMPTY_VALUE = ""


class ReceiptVerifierRegistration(models.Model):
    """A durable verifier binding for one materialized range assignment."""

    class Status(models.TextChoices):
        """Lifecycle state for a verifier registration."""

        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    range = models.ForeignKey(
        "engine.Range",
        on_delete=models.CASCADE,
        related_name="receipt_verifier_registrations",
    )
    registration_revision = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    materialization_id = models.UUIDField(editable=False)
    provisioning_operation_id = models.UUIDField(editable=False)
    assignment_epoch = models.UUIDField(default=uuid.uuid4, editable=False)
    deployment_id = models.CharField(max_length=128)
    profile_id = models.CharField(max_length=128)
    provider_contract = models.CharField(max_length=128)
    ctf_event_id = models.UUIDField()
    ctf_participant_id = models.UUIDField()
    objectives = models.JSONField(help_text="Bounded objective identifiers admitted for this assignment")
    issuer_id = models.CharField(max_length=128)
    provider_range_namespace = models.CharField(max_length=128)
    provider_participant_namespace = models.CharField(max_length=128)
    key_mode = models.CharField(
        max_length=32,
        choices=[(mode.value, mode.value) for mode in ReceiptKeyMode],
    )
    algorithm_id = models.CharField(max_length=128)
    key_id = models.CharField(max_length=128)
    secret_version_ref = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Provider secret version reference; never projected to CTF",
    )
    public_verification_key = models.TextField(blank=True, default="")
    reset_generation = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Persist one active binding while retaining revoked assignment history."""

        db_table = "engine_receipt_verifier_registration"
        ordering = ["range", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["range"],
                condition=models.Q(status="active"),
                name="engine_one_active_receipt_verifier_per_range",
            ),
            models.UniqueConstraint(
                fields=["range", "assignment_epoch"],
                name="engine_receipt_assignment_epoch_identity",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        key_mode=ReceiptKeyMode.REMOTE_SYMMETRIC.value,
                        public_verification_key="",
                    )
                    & ~models.Q(secret_version_ref=_EMPTY_VALUE)
                    | models.Q(
                        key_mode=ReceiptKeyMode.ASYMMETRIC_PUBLIC.value,
                        secret_version_ref=_EMPTY_VALUE,
                    )
                    & ~models.Q(public_verification_key="")
                ),
                name="engine_receipt_verifier_key_shape",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="active", revoked_at__isnull=True)
                    | models.Q(status="revoked", revoked_at__isnull=False)
                ),
                name="engine_receipt_verifier_status_timestamp",
            ),
        ]

    def __str__(self) -> str:
        """Return a non-secret registration identifier for operator diagnostics."""
        return f"ReceiptVerifierRegistration({self.registration_revision}, {self.status})"
