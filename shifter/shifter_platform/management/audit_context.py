"""Request attribution value objects for management mutations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditContext:
    """Request-attributed audit fields bundled for account-mutation services."""

    actor_type: str
    actor_id: int | None
    request_id: str = ""
    source_ip: str | None = None
    user_agent: str = ""
