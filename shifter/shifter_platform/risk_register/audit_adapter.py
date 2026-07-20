"""Concrete audit persistence adapter (risk-register domain).

Binds the neutral ``shared.audit`` writer port to the durable ``AuditLog`` table.
This is the ONLY place ``AuditLog.log()`` is called at runtime (#1523): emitters
depend on the port, and ``config`` binds this adapter at startup. The adapter
owns ORM mapping and persistence only; it raises persistence faults up to the
shared emission policy and never adds a second catch/swallow hierarchy.
"""

from __future__ import annotations

from risk_register.models import AuditLog
from shared.audit import AuditEvent


class DjangoAuditLogWriter:
    """Persist :class:`~shared.audit.AuditEvent` rows to ``risk_register.AuditLog``.

    Satisfies the ``shared.audit.AuditWriter`` port structurally. ``write`` is a
    static method because the mapping is stateless; instances still expose it as
    a callable ``.write(event)``, so the port binding is unchanged.
    """

    @staticmethod
    def write(event: AuditEvent) -> None:
        """Map an audit event onto the durable ``AuditLog`` row.

        Raises whatever the ORM raises on a persistence failure; the shared
        emission policy decides whether that is best-effort or fail-closed.
        """
        AuditLog.log(
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


# Module-level singleton so the startup binding is stable and idempotent.
audit_log_writer = DjangoAuditLogWriter()
