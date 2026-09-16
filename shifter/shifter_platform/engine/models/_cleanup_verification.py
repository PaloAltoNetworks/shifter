"""Durable, scoped provider inventory/readback evidence for a range teardown.

ADR-063-R4/R5 (#2086). Verified terminal cleanup is not a logical lifecycle
status: it requires the owning lifecycle to succeed AND an independent
inventory/readback of the owned provider resources, carrying scope and an
observation time. This row is that evidence, produced from the provisioner's
post-teardown inventory and recorded by the Engine applier.

It is NOT a second operation state model (ADR-043-R4): it never drives the
operation lifecycle. It is append-only cleanup evidence keyed to the existing
request and operation generation; a later re-inventory supersedes the current
outcome (a residual discovered later corrects the projection) without rewriting
history. ``verified_terminal`` reporting, retry-binding pruning, and CTF
capacity/linkage release all gate on the latest record being ``VERIFIED_ABSENT``.
"""

from django.db import models


class CleanupVerificationOutcome(models.TextChoices):
    """Outcome of a scoped provider inventory/readback after teardown."""

    VERIFIED_ABSENT = "VERIFIED_ABSENT", "Verified absent"
    RESIDUALS_FOUND = "RESIDUALS_FOUND", "Residuals found"
    # The inventory could not complete (unavailable provider/credentials/scope).
    # Unknown, never an empty success: obligations and evidence are retained.
    INCOMPLETE = "INCOMPLETE", "Incomplete inventory"


class RangeCleanupVerification(models.Model):
    """Scoped provider inventory/readback evidence for one teardown observation."""

    request_id = models.UUIDField(db_index=True)
    operation_id = models.UUIDField(db_index=True)
    outcome = models.CharField(max_length=24, choices=CleanupVerificationOutcome.choices)
    # What was inventoried: resource categories plus provider scope (project/zone)
    # at observation time. Non-secret; no resource/credential locators.
    scope = models.JSONField()
    # Residual resource categories/counts still present when RESIDUALS_FOUND.
    # Authorized categories/counts only -- never locators or diagnostics.
    residual_categories = models.JSONField(default=list)
    # Provider observation time carried by the inventory, distinct from created_at.
    observed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table configuration for range cleanup verification evidence."""

        db_table = "engine_range_cleanup_verification"
        indexes = [
            models.Index(fields=["request_id", "created_at"], name="engine_cleanupver_req_idx"),
        ]

    def __str__(self) -> str:
        return f"RangeCleanupVerification {self.request_id} ({self.outcome})"
