"""Audit event and context value objects (neutral contracts layer).

These frozen dataclasses are the cohesive shapes emitters pass to the audit
port. They carry only bounded, JSON-safe summaries — never tokens, cookies,
credentials, raw headers, or provider payloads (#1523).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuditEvent:
    """A single auditable event passed to :func:`shared.audit.audit_log`.

    Groups the entity, actor, state-change and request-context fields so the
    port takes one cohesive object instead of a long parameter list.
    """

    entity_type: str
    entity_id: int
    action: str
    actor_type: str = "system"
    actor_id: int | None = None
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    context: str = ""
    source_ip: str | None = None
    user_agent: str = ""
    request_id: str = ""


@dataclass(frozen=True)
class StateChange:
    """Before/after entity state for a system audit event."""

    previous: dict[str, Any] | None = None
    new: dict[str, Any] | None = None


@dataclass(frozen=True)
class RequestAudit:
    """Request-derived audit context (source IP, user agent, request id)."""

    source_ip: str | None = None
    user_agent: str = ""
    request_id: str = ""


@dataclass(frozen=True)
class AuthPrincipal:
    """Identity of the principal in an authentication audit event."""

    user_id: int | None = None
    email: str = ""
    cognito_sub: str = ""


@dataclass(frozen=True)
class SessionInfo:
    """Session details for a session audit event."""

    session_id: str
    range_id: int | None = None
    session_type: str = ""
    target_ip: str = ""
    email: str = ""
