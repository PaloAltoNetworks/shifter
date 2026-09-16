"""Operation-boundary persistence: immutable input projection + result inbox.

ADR-043 Phase 2 (#1834). The engine materializes one immutable, versioned
operation-input projection keyed by the canonical ``operation_id`` (created in
the same transaction as the launch intent), and the provisioner appends versioned
results to a dedicated append-only inbox. An engine-owned applier validates and
records a disposition. For operation families with a declared step contract, the
applier authoritatively mutates domain state, audits the transition, and enqueues
range events in one transaction. Families that have not cut over retain direct
provisioner SQL and receive a validation-only shadow disposition.

Both tables carry the transport envelope (validated by
``shared.operation_envelope``) plus flattened discriminator columns for indexing
and fencing. They are operation contracts, not ORM/table projections.
"""

from django.db import models


class OperationResultKind(models.TextChoices):
    """Closed vocabulary for a provisioner result's role in an operation."""

    PROGRESS = "PROGRESS", "Progress"
    RESOURCE_STATE = "RESOURCE_STATE", "Resource state"
    TERMINAL_SUCCESS = "TERMINAL_SUCCESS", "Terminal success"
    TERMINAL_FAILURE = "TERMINAL_FAILURE", "Terminal failure"


class OperationResultDisposition(models.TextChoices):
    """Applier disposition for an inbox result, distinct from range status.

    ``VALIDATED`` marks a compatibility-family shadow result; authoritative
    families finish as ``APPLIED`` or a fail-closed rejection.
    """

    PENDING = "PENDING", "Pending"
    VALIDATED = "VALIDATED", "Validated (shadow)"
    REJECTED_STALE = "REJECTED_STALE", "Rejected: stale operation generation"
    REJECTED_OWNERSHIP = "REJECTED_OWNERSHIP", "Rejected: wrong resource ownership"
    REJECTED_VERSION = "REJECTED_VERSION", "Rejected: unsupported contract version"
    REJECTED_CONFLICT = "REJECTED_CONFLICT", "Rejected: conflicting replay"
    REJECTED_INVALID = "REJECTED_INVALID", "Rejected: invalid payload"
    REJECTED_ORDERING = "REJECTED_ORDERING", "Rejected: illegal step order for the operation"
    APPLIED = "APPLIED", "Applied to domain state"


class OperationInput(models.Model):
    """Immutable, versioned operation input keyed by ``operation_id``.

    Created once, in the launch-intent transaction. The provisioner reads exactly
    this row by ``operation_id`` (never "latest by request"). Never updated.
    """

    operation_id = models.UUIDField(editable=False, unique=True)
    request_id = models.UUIDField(editable=False, db_index=True)
    resource = models.CharField(max_length=32)
    operation = models.CharField(max_length=32)
    contract_version = models.CharField(max_length=16)
    envelope = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Table configuration for immutable operation inputs."""

        db_table = "engine_operation_input"

    def __str__(self) -> str:
        return f"OperationInput {self.operation_id} ({self.resource}:{self.operation})"


class OperationResultInbox(models.Model):
    """Append-only, versioned provisioner result with idempotent identity.

    ``result_identity`` is a deterministic per-result key (unique). A repeat with
    the same identity and ``payload_digest`` is a harmless replay; the same
    identity with a different digest is a conflict that must fail closed
    (``ON CONFLICT DO NOTHING`` alone is insufficient). ``operation_id`` is the
    generation fence the applier checks against the current domain row.
    """

    operation_id = models.UUIDField(editable=False, db_index=True)
    request_id = models.UUIDField(editable=False, db_index=True)
    resource = models.CharField(max_length=32)
    operation = models.CharField(max_length=32)
    contract_version = models.CharField(max_length=16)
    result_kind = models.CharField(max_length=32, choices=OperationResultKind.choices)
    # Closed per-operation step key (``shared.operation_results.ResultStep``).
    # One operation emits several results of the same kind, so the step — not the
    # kind — is what orders them and what a conflicting replay collides on. Blank
    # on pre-cutover shadow rows, which the authoritative applier will not apply.
    result_step = models.CharField(max_length=48, blank=True, default="", db_index=True)
    result_identity = models.CharField(max_length=255, unique=True)
    # "sha256:" prefix + 64 hex characters
    payload_digest = models.CharField(max_length=71)
    envelope = models.JSONField()
    disposition = models.CharField(
        max_length=24,
        default=OperationResultDisposition.PENDING,
        choices=OperationResultDisposition.choices,
        db_index=True,
    )
    disposition_detail = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Table configuration for the append-only operation result inbox."""

        db_table = "engine_operation_result_inbox"
        indexes = [
            models.Index(fields=["operation_id", "created_at"], name="engine_opresult_op_seq_idx"),
            models.Index(fields=["disposition", "created_at"], name="engine_opresult_disp_idx"),
        ]

    def __str__(self) -> str:
        return f"OperationResultInbox {self.result_identity} ({self.disposition})"
