"""Neutral audit boundary for the whole platform (#1523, ADR-001).

``shared.audit`` is the single audit contract every layer emits through. It owns
the canonical vocabulary, the event/context shapes, the writer port + startup
binding, the strict/best-effort emission policy, trusted request attribution,
and process-local health. The concrete persistence adapter lives alongside this
boundary in ``shared.audit_adapter`` and is bound to the port at startup.
"""

from __future__ import annotations

from shared.audit.attribution import (
    get_actor_from_request,
    get_client_ip,
    get_request_id,
    principal_actor_fields,
    request_audit,
    select_trusted_client_ip,
)
from shared.audit.events import (
    AuditEvent,
    AuthPrincipal,
    RequestAudit,
    SessionInfo,
    StateChange,
)
from shared.audit.health import (
    AuditHealthSnapshot,
    get_audit_health_snapshot,
    mark_audit_degraded,
    reset_audit_health,
)
from shared.audit.policy import (
    AuditTarget,
    audit_auth_event,
    audit_log,
    audit_log_from_request,
    audit_log_system_event,
    audit_role_sync,
    audit_session_event,
)
from shared.audit.port import (
    AuditWriter,
    AuditWriterBindingError,
    bind_audit_writer,
    get_audit_writer,
    reset_audit_writer,
)
from shared.audit.query import AuditReadDenied, authorized_audit_events
from shared.audit.vocabulary import (
    API_KEY_LABEL,
    AuditAction,
    AuditActorType,
    AuditEntityType,
)

__all__ = [
    "API_KEY_LABEL",
    "AuditAction",
    "AuditActorType",
    "AuditEntityType",
    "AuditEvent",
    "AuditHealthSnapshot",
    "AuditReadDenied",
    "AuditTarget",
    "AuditWriter",
    "AuditWriterBindingError",
    "AuthPrincipal",
    "RequestAudit",
    "SessionInfo",
    "StateChange",
    "audit_auth_event",
    "audit_log",
    "audit_log_from_request",
    "audit_log_system_event",
    "audit_role_sync",
    "audit_session_event",
    "authorized_audit_events",
    "bind_audit_writer",
    "get_actor_from_request",
    "get_audit_health_snapshot",
    "get_audit_writer",
    "get_client_ip",
    "get_request_id",
    "mark_audit_degraded",
    "principal_actor_fields",
    "request_audit",
    "reset_audit_health",
    "reset_audit_writer",
    "select_trusted_client_ip",
]
