"""Django persistence adapter for the shared audit boundary."""

from __future__ import annotations

from shared.audit import AuditEvent
from shared.models import AuditLog


class DjangoAuditLogWriter:
    """Persist audit events in the platform-owned durable store."""

    @staticmethod
    def write(event: AuditEvent) -> None:
        """Map an audit event onto a durable row."""
        AuditLog.objects.create(
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            action=event.action,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            previous_state=event.previous_state,
            new_state=event.new_state,
            context=event.context,
            source_ip=event.source_ip,
            user_agent=event.user_agent,
            request_id=event.request_id,
        )


audit_log_writer = DjangoAuditLogWriter()
