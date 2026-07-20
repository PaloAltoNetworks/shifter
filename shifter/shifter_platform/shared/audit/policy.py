"""Audit emission policy (neutral contracts layer).

The single entry point every layer uses to record an auditable event. This
module owns the strict-versus-best-effort failure policy, sanitized operational
logging, and process-local degradation marking; it delegates durable
persistence to the bound :class:`~shared.audit.port.AuditWriter`. It never
returns an ORM object across the port — callers observe durable behavior by
querying the owning read surface (#1523).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from shared.audit.attribution import (
    get_actor_from_request,
    get_client_ip,
    get_request_id,
)
from shared.audit.events import AuditEvent, AuthPrincipal, RequestAudit, SessionInfo, StateChange
from shared.audit.health import mark_audit_degraded
from shared.audit.port import get_audit_writer
from shared.audit.vocabulary import AuditAction, AuditActorType, AuditEntityType
from shared.log_sanitize import safe_log_fingerprint

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def audit_log(event: AuditEvent, *, strict: bool = False) -> bool:
    """Record an audit event through the bound writer.

    Called by all platform layers for auditable operations.

    Args:
        event: The auditable event to record (see :class:`AuditEvent`).
        strict: When True, re-raise on persistence failure instead of swallowing
            it. The default (False) preserves the "audit logging never breaks the
            caller" contract; ``strict=True`` is for fail-closed paths where the
            audit row is the safety control and the caller rolls back the mutation
            it describes if the row cannot be written (issue #937 SEC-5).

    Returns:
        True when the event was persisted; False when a non-strict write failed.
    """
    action = event.action
    entity_type = event.entity_type
    entity_id = event.entity_id
    actor_type = event.actor_type
    try:
        get_audit_writer().write(event)
        # CodeQL's ``py/clear-text-logging-sensitive-data`` taints these fields
        # on dataflow grounds because some call sites also pass credential-bearing
        # ``previous_state`` / ``new_state`` dicts. action / entity_type /
        # entity_id / actor_type are enum strings and integers, never credentials.
        # The sanitizing transform must be applied INLINE in the logger argument
        # (not at a prior assignment) for CodeQL's clear-text rule to recognise it
        # as breaking the flow; the shared ``safe_log_value`` helper is opaque to
        # the rule, so it cannot be used here. ``actor_id`` is derived from
        # authenticated-principal state at some call sites, so it goes through
        # ``safe_log_fingerprint`` — a value-independent nonce that is a true
        # taint-break; the authoritative id is retained on the durable
        # ``AuditLog`` row, so a correlation token suffices in this debug log.
        op_name = str(action)
        op_target_kind = str(entity_type)
        op_target_id = str(entity_id)
        op_actor_kind = str(actor_type)
        logger.debug(
            "Audit logged: %s %s %s by %s:%s",
            op_name.replace("\r", " ").replace("\n", " ")[:100],
            op_target_kind.replace("\r", " ").replace("\n", " ")[:100],
            op_target_id.replace("\r", " ").replace("\n", " ")[:100],
            op_actor_kind.replace("\r", " ").replace("\n", " ")[:100],
            safe_log_fingerprint(event.actor_id),
        )
        return True
    except Exception as exc:
        mark_audit_degraded(exc)
        # Audit logging should never break the application
        op_name = str(action).replace("\r", " ").replace("\n", " ")[:100]
        op_target_kind = str(entity_type).replace("\r", " ").replace("\n", " ")[:100]
        op_target_id = str(entity_id).replace("\r", " ").replace("\n", " ")[:100]
        logger.exception(
            "Failed to create audit log: action=%s entity_type=%s entity_id=%s",
            op_name,
            op_target_kind,
            op_target_id,
        )
        if strict:
            raise
        return False


def audit_role_sync(
    *,
    user_id: int,
    actor_type: str,
    actor_id: int | None,
    change: StateChange,
    source: str,
    request: RequestAudit | None = None,
) -> bool:
    """Record a ``user_type`` / CTF-group-membership change (fail-closed).

    The safety control for the self-mutable ``custom:user_type`` attribute is a
    durable, reviewable audit trail (issue #937 SEC-5), so this writer is
    strict: a persistence failure raises rather than returning False, so callers
    running it inside a transaction roll back the role mutation it describes.
    ``change`` carries the old and new ``user_type`` plus the old and new CTF
    group names — never tokens, cookies, or raw provider payloads.
    """
    request = request or RequestAudit()
    return audit_log(
        AuditEvent(
            entity_type=AuditEntityType.USER,
            entity_id=user_id,
            action=AuditAction.ROLE_SYNC,
            actor_type=actor_type,
            actor_id=actor_id,
            previous_state=change.previous,
            new_state=change.new,
            context=f"user_type sync via {source}",
            source_ip=request.source_ip,
            user_agent=request.user_agent,
            request_id=request.request_id,
        ),
        strict=True,
    )


def audit_log_from_request(
    request: HttpRequest,
    entity_type: str,
    entity_id: int,
    action: str,
    *,
    previous_state: dict[str, Any] | None = None,
    new_state: dict[str, Any] | None = None,
    context: str = "",
) -> bool:
    """Record audit event with HTTP request context.

    Extracts user/apikey, source IP, user agent, and request ID from the
    request object.

    Args:
        request: Django HttpRequest
        entity_type: Type of entity (use AuditEntityType values)
        entity_id: ID of the entity being acted upon
        action: Action performed (use AuditAction values)
        previous_state: Entity state before the action
        new_state: Entity state after the action
        context: Additional context or reason

    Returns:
        True when the event was persisted; False on non-strict failure.
    """
    actor_type, actor_id = get_actor_from_request(request)

    return audit_log(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            previous_state=previous_state,
            new_state=new_state,
            context=context,
            source_ip=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            request_id=get_request_id(request),
        )
    )


def audit_log_system_event(
    entity_type: str,
    entity_id: int,
    action: str,
    source: str,
    *,
    state: StateChange | None = None,
    context: str = "",
    request_id: str = "",
) -> bool:
    """Record system-initiated audit event.

    For provisioner, event handlers, scheduled tasks, and other background
    processes.

    Args:
        entity_type: Type of entity
        entity_id: ID of the entity
        action: Action performed
        source: Source of the event (e.g., "engine.handlers", "provisioner")
        state: Before/after entity state (see :class:`StateChange`)
        context: Additional context
        request_id: Optional request ID for correlation

    Returns:
        True when the event was persisted; False on non-strict failure.
    """
    full_context = f"[{source}] {context}" if context else f"[{source}]"
    state = state or StateChange()

    return audit_log(
        AuditEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            previous_state=state.previous,
            new_state=state.new,
            context=full_context,
            request_id=request_id,
        )
    )


def audit_auth_event(
    action: str,
    *,
    principal: AuthPrincipal | None = None,
    source_ip: str | None = None,
    user_agent: str = "",
    context: str = "",
    actor_type: str = AuditActorType.COGNITO,
) -> bool:
    """Record authentication event.

    Args:
        action: login, logout, login_failed
        principal: Identity of the authenticating principal
            (see :class:`AuthPrincipal`)
        source_ip: Client IP
        user_agent: Client user agent
        context: Additional context (e.g., failure reason)
        actor_type: Type of auth (cognito, apikey)

    Returns:
        True when the event was persisted; False on non-strict failure.
    """
    principal = principal or AuthPrincipal()
    new_state: dict[str, Any] = {}
    if principal.email:
        new_state["email"] = principal.email
    if principal.cognito_sub:
        new_state["cognito_sub"] = principal.cognito_sub

    return audit_log(
        AuditEvent(
            entity_type=AuditEntityType.USER,
            entity_id=principal.user_id or 0,
            action=action,
            actor_type=actor_type,
            actor_id=None,
            new_state=new_state if new_state else None,
            context=context,
            source_ip=source_ip,
            user_agent=user_agent,
        )
    )


def audit_session_event(
    action: str,
    *,
    user_id: int,
    session: SessionInfo,
    source_ip: str | None = None,
    context: str = "",
) -> bool:
    """Record session event (terminal/RDP connect/disconnect).

    Args:
        action: connect, disconnect, access_denied
        user_id: User ID
        session: Session details (see :class:`SessionInfo`)
        source_ip: Client IP
        context: Additional context

    Returns:
        True when the event was persisted; False on non-strict failure.
    """
    new_state: dict[str, Any] = {
        "session_id": session.session_id,
    }
    if session.range_id:
        new_state["range_id"] = session.range_id
    if session.session_type:
        new_state["session_type"] = session.session_type
    if session.target_ip:
        new_state["target_ip"] = session.target_ip
    if session.email:
        new_state["email"] = session.email

    # Sessions don't have persistent IDs
    return audit_log(
        AuditEvent(
            entity_type=AuditEntityType.SESSION,
            entity_id=0,
            action=action,
            actor_type=AuditActorType.USER,
            actor_id=user_id,
            new_state=new_state,
            context=context,
            source_ip=source_ip,
        )
    )
