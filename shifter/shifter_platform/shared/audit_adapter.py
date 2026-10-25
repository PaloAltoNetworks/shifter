"""Django persistence adapter for the shared audit boundary."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.audit import AuditEvent
from shared.audit.integrity import (
    CANONICALIZATION_VERSION,
    CHAIN_GENERATION,
    CHAIN_HEAD_SINGLETON,
    AuditIntegrityError,
    canonical_record_digest,
    validate_audit_event,
)
from shared.deployment import resolve_audit_deployment_scope
from shared.models import AuditChainHead, AuditLog


class DjangoAuditLogWriter:
    """Persist audit events in the platform-owned durable store."""

    @staticmethod
    def write(event: AuditEvent) -> None:
        """Validate and append one event under the database-owned chain lock."""
        append_audit_event(event)


def append_audit_event(
    event: AuditEvent,
    *,
    recorded_at: datetime | None = None,
    event_id: uuid.UUID | None = None,
) -> AuditLog:
    """Append and return one validated event.

    The optional identities support deterministic migrations and tests. Runtime
    emitters use :class:`DjangoAuditLogWriter`, which supplies neither.
    """
    validate_audit_event(event)
    deployment_scope = resolve_audit_deployment_scope()
    recorded_at = recorded_at or timezone.now()
    event_id = event_id or uuid.uuid4()

    with transaction.atomic():
        try:
            head = AuditChainHead.objects.select_for_update().get(singleton=CHAIN_HEAD_SINGLETON)
        except AuditChainHead.DoesNotExist:
            # Normal deployed databases receive the singleton in the integrity
            # migration. This path supports empty test databases and fails
            # safely under a first-write race.
            try:
                with transaction.atomic():
                    AuditChainHead.objects.create(
                        singleton=CHAIN_HEAD_SINGLETON,
                        deployment_scope=deployment_scope,
                        chain_generation=CHAIN_GENERATION,
                        canonicalization_version=CANONICALIZATION_VERSION,
                    )
            except IntegrityError:
                pass
            head = AuditChainHead.objects.select_for_update().get(singleton=CHAIN_HEAD_SINGLETON)

        if head.deployment_scope != deployment_scope:
            if head.last_sequence == 0 and head.last_digest == "":
                # The migration creates the serialization row even for an empty
                # ledger. Bind that empty head to the effective deployment on
                # the first append; no committed evidence changes identity.
                head.deployment_scope = deployment_scope
                head.save(update_fields=["deployment_scope", "updated_at"])
            else:
                raise AuditIntegrityError("audit chain deployment scope does not match this deployment")
        if head.chain_generation != CHAIN_GENERATION:
            raise AuditIntegrityError("audit chain generation is unsupported")
        if head.canonicalization_version != CANONICALIZATION_VERSION:
            raise AuditIntegrityError("audit canonicalization version is unsupported")

        sequence = head.last_sequence + 1
        record = {
            "event_id": event_id,
            "deployment_scope": deployment_scope,
            "chain_generation": head.chain_generation,
            "sequence": sequence,
            "canonicalization_version": head.canonicalization_version,
            "recorded_at": recorded_at,
            "previous_digest": head.last_digest,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "entity_ref": event.entity_ref,
            "action": event.action,
            "actor_type": event.actor_type,
            "actor_id": event.actor_id,
            "actor_principal_uuid": event.actor_principal_uuid,
            "previous_state": event.previous_state,
            "new_state": event.new_state,
            "context": event.context,
            "source_ip": event.source_ip,
            "user_agent": event.user_agent,
            "request_id": event.request_id,
        }
        record_digest = canonical_record_digest(record)
        row = AuditLog.objects.create(
            event_id=event_id,
            deployment_scope=deployment_scope,
            chain_generation=head.chain_generation,
            sequence=sequence,
            canonicalization_version=head.canonicalization_version,
            previous_digest=head.last_digest,
            record_digest=record_digest,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            entity_ref=event.entity_ref,
            action=event.action,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            actor_principal_uuid=event.actor_principal_uuid,
            timestamp=recorded_at,
            previous_state=event.previous_state,
            new_state=event.new_state,
            context=event.context,
            source_ip=event.source_ip,
            user_agent=event.user_agent,
            request_id=event.request_id,
        )
        head.last_sequence = sequence
        head.last_digest = record_digest
        head.save(update_fields=["last_sequence", "last_digest", "updated_at"])
        return row


audit_log_writer = DjangoAuditLogWriter()
