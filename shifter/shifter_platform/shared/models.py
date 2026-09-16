"""Shared Django models."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

# ApiToken lives in the cohesive shared.api_tokens package but belongs to the
# ``shared`` app; importing it here ensures Django discovers it and emits its
# migration under shared/migrations/.
from shared.api_tokens.models import ApiToken  # noqa: F401
from shared.audit import AuditAction, AuditActorType, AuditEntityType


class WebSocketNotification(models.Model):
    """Durable per-recipient queue for browser WebSocket notifications."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="websocket_notifications",
    )
    event_id = models.UUIDField(default=uuid.uuid4)
    notification_type = models.CharField(max_length=128, db_index=True)
    topic = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(blank=True, null=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        """Model metadata."""

        db_table = "shared_websocket_notification"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["recipient", "topic", "delivered_at"], name="wsn_rec_topic_delivery_idx"),
            models.Index(fields=["expires_at"], name="wsn_expires_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "topic", "notification_type", "event_id"],
                name="uniq_wsn_rec_topic_type_event",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.notification_type}:{self.topic}:{self.recipient_id}"


class RaesOperationRecord(models.Model):
    """First-class RAES operation sidecar record keyed by Shifter request_id."""

    class ContractKind(models.TextChoices):
        """Supported operation sidecar contract families."""

        RAES = "raes", "RAES"

    class RecordKind(models.TextChoices):
        """Supported operation sidecar record kinds."""

        OPERATION_RECEIPT = "operation_receipt", "Operation receipt"
        OPERATION_STATUS = "operation_status", "Operation status"
        RUNTIME_SNAPSHOT = "runtime_snapshot", "Runtime snapshot"
        EXECUTION_PLAN_REF = "execution_plan_ref", "Execution-plan reference"

    class Owner(models.TextChoices):
        """Component boundary that owns the write contract for a row."""

        SHARED = "shared", "Shared RAES boundary"
        ENGINE = "engine", "Engine service"
        PROVISIONER = "provisioner", "Provisioner"
        CMS = "cms", "CMS service"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(db_index=True, help_text="Shifter operation correlation key")
    range_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Optional range projection/backfill key; not the operation key",
    )
    operation_id = models.CharField(max_length=128, db_index=True)
    idempotency_key = models.CharField(max_length=128)
    contract_kind = models.CharField(max_length=32, choices=ContractKind.choices, default=ContractKind.RAES)
    contract_version = models.CharField(max_length=64, db_index=True)
    contract_profile = models.CharField(max_length=64, db_index=True)
    record_kind = models.CharField(max_length=32, choices=RecordKind.choices, db_index=True)
    source_timestamp = models.DateTimeField(db_index=True)
    payload_digest = models.CharField(max_length=71)
    payload = models.JSONField(default=dict, help_text="Validated canonical RAES payload or bounded reference payload")
    diagnostic_refs = models.JSONField(
        default=dict,
        blank=True,
        help_text="Sanitized diagnostic references only; no provider dumps, tokens, or embedded output",
    )
    owner = models.CharField(max_length=32, choices=Owner.choices, default=Owner.SHARED, db_index=True)
    retention_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        db_table = "shared_raes_operation_record"
        ordering = ["-source_timestamp", "-created_at"]
        indexes = [
            models.Index(fields=["request_id", "record_kind", "source_timestamp"], name="raesop_req_kind_src_idx"),
            models.Index(fields=["operation_id", "record_kind"], name="raesop_op_kind_idx"),
            models.Index(fields=["retention_expires_at"], name="raesop_retention_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["request_id", "record_kind", "contract_version", "contract_profile", "idempotency_key"],
                name="uniq_raesop_idempotency",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.record_kind}:{self.request_id}:{self.idempotency_key}"

    def save(self, *args, **kwargs) -> None:
        """Persist after enforcing the sidecar validation contract."""
        from shared.schemas.raes_operation import RaesOperationRecordData, validate_raes_operation_record

        result = validate_raes_operation_record(
            RaesOperationRecordData(
                request_id=self.request_id,
                range_id=self.range_id,
                operation_id=self.operation_id,
                idempotency_key=self.idempotency_key,
                record_kind=self.record_kind,
                contract_kind=self.contract_kind,
                contract_version=self.contract_version,
                contract_profile=self.contract_profile,
                source_timestamp=self.source_timestamp,
                payload_digest=self.payload_digest,
                payload=self.payload,
                diagnostic_refs=self.diagnostic_refs,
                owner=self.owner,
            )
        )
        self.payload = result.payload
        self.diagnostic_refs = result.diagnostic_refs
        super().save(*args, **kwargs)


class RaesParticipantRuntimeRecord(models.Model):
    """First-class RAES participant-runtime sidecar record (#1288).

    Mirrors :class:`RaesOperationRecord` (the incumbent sidecar pattern from
    #1273/#1274/#1275). Keyed by Shifter ``request_id`` plus a bounded
    ``participant_ref`` correlation reference; ``participant_ref`` alone is
    never the identity (see the preflight note). This is a first-class
    storage/read-projection slice: it must not carry lifecycle, access,
    scoring, challenge, experiment, terminal, Guacamole, or range authority.
    """

    class ContractKind(models.TextChoices):
        """Supported participant-runtime sidecar contract families."""

        RAES = "raes", "RAES"

    class RecordKind(models.TextChoices):
        """Supported participant-runtime sidecar record kinds."""

        PARTICIPANT_IMPLEMENTATION = "participant_implementation", "Participant implementation"
        PARTICIPANT_RUNTIME = "participant_runtime", "Participant runtime"
        PARTICIPANT_BEHAVIOR_HISTORY = "participant_behavior_history", "Participant behavior history"
        PARTICIPANT_EVIDENCE = "participant_evidence", "Participant evidence"

    class Owner(models.TextChoices):
        """Component boundary that owns the write contract for a row."""

        SHARED = "shared", "Shared RAES boundary"
        ENGINE = "engine", "Engine service"
        PROVISIONER = "provisioner", "Provisioner"
        CMS = "cms", "CMS service"
        CTF = "ctf", "CTF service"

    class RetentionClass(models.TextChoices):
        """Retention policy class; a small validated vocabulary."""

        DEFAULT = "default", "Default retention"

    class RedactionState(models.TextChoices):
        """Redaction state of the persisted payload; a small validated vocabulary."""

        SANITIZED = "sanitized", "Sanitized"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(db_index=True, help_text="Shifter operation correlation key")
    range_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Optional range projection/backfill key; not the participant identity",
    )
    range_instance_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Optional range-instance projection/backfill key; not the participant identity",
    )
    participant_ref = models.CharField(
        max_length=256,
        db_index=True,
        help_text="Bounded participant correlation reference; never alone the identity",
    )
    idempotency_key = models.CharField(max_length=128)
    contract_kind = models.CharField(max_length=32, choices=ContractKind.choices, default=ContractKind.RAES)
    contract_version = models.CharField(max_length=64, db_index=True)
    contract_profile = models.CharField(max_length=64, db_index=True)
    participant_runtime_profile = models.CharField(max_length=64, db_index=True)
    record_kind = models.CharField(max_length=32, choices=RecordKind.choices, db_index=True)
    source_timestamp = models.DateTimeField(db_index=True)
    payload_digest = models.CharField(max_length=71)
    payload = models.JSONField(
        default=dict, help_text="Validated canonical RAES participant-runtime payload or bounded reference payload"
    )
    diagnostic_refs = models.JSONField(
        default=dict,
        blank=True,
        help_text="Sanitized diagnostic references only; no provider dumps, tokens, or embedded output",
    )
    owner = models.CharField(max_length=32, choices=Owner.choices, default=Owner.SHARED, db_index=True)
    retention_class = models.CharField(max_length=32, choices=RetentionClass.choices, default=RetentionClass.DEFAULT)
    retention_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    redaction_state = models.CharField(max_length=32, choices=RedactionState.choices, default=RedactionState.SANITIZED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        db_table = "shared_raes_participant_runtime_record"
        ordering = ["-source_timestamp", "-created_at"]
        indexes = [
            models.Index(fields=["request_id", "record_kind", "source_timestamp"], name="raespr_req_kind_src_idx"),
            models.Index(fields=["participant_ref", "record_kind"], name="raespr_ref_kind_idx"),
            models.Index(fields=["retention_expires_at"], name="raespr_retention_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "request_id",
                    "participant_ref",
                    "record_kind",
                    "participant_runtime_profile",
                    "contract_version",
                    "idempotency_key",
                ],
                name="uniq_raespr_idempotency",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.record_kind}:{self.request_id}:{self.participant_ref}:{self.idempotency_key}"

    def save(self, *args, **kwargs) -> None:
        """Persist after enforcing the sidecar validation contract."""
        from shared.schemas.raes_participant_runtime import (
            RaesParticipantRuntimeRecordData,
            validate_raes_participant_runtime_record,
        )

        result = validate_raes_participant_runtime_record(
            RaesParticipantRuntimeRecordData(
                request_id=self.request_id,
                range_id=self.range_id,
                range_instance_id=self.range_instance_id,
                participant_ref=self.participant_ref,
                idempotency_key=self.idempotency_key,
                record_kind=self.record_kind,
                contract_kind=self.contract_kind,
                contract_version=self.contract_version,
                contract_profile=self.contract_profile,
                participant_runtime_profile=self.participant_runtime_profile,
                source_timestamp=self.source_timestamp,
                payload_digest=self.payload_digest,
                payload=self.payload,
                diagnostic_refs=self.diagnostic_refs,
                owner=self.owner,
                retention_class=self.retention_class,
                redaction_state=self.redaction_state,
            )
        )
        self.payload = result.payload
        self.diagnostic_refs = result.diagnostic_refs
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    """Immutable durable record of a platform audit event."""

    entity_type = models.CharField(max_length=20, choices=AuditEntityType.choices)
    entity_id = models.PositiveIntegerField()
    action = models.CharField(max_length=20, choices=AuditAction.choices)
    actor_type = models.CharField(max_length=10, choices=AuditActorType.choices)
    actor_id = models.PositiveIntegerField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    previous_state = models.JSONField(null=True, blank=True)
    new_state = models.JSONField(null=True, blank=True)
    context = models.TextField(blank=True, help_text="Optional reason or notes")
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)

    class Meta:
        """Keep the shared audit table stable and queryable."""

        db_table = "shared_auditlog"
        ordering = ["-timestamp"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"], name="shared_audit_entity_idx"),
            models.Index(fields=["actor_type", "actor_id"], name="shared_audit_actor_idx"),
            models.Index(fields=["timestamp"], name="shared_audit_timestamp_idx"),
            models.Index(fields=["action"], name="shared_audit_action_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type} {self.entity_id} at {self.timestamp}"
