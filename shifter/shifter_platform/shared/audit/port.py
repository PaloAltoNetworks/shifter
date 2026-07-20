"""Audit writer port and startup binding (neutral contracts layer).

The audit port inverts the historical dependency: emitters depend on this
neutral protocol, and the concrete persistence adapter (``risk_register``) is
bound to it once at startup (``config.apps.PortalConfig.ready``). The single
binding is the extensibility seam — a future writer is selected without changing
any emitter. A missing or conflicting binding is a startup configuration error,
never a silent no-op (#1523).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from shared.audit.events import AuditEvent


class AuditWriterBindingError(RuntimeError):
    """Raised when the audit writer binding is missing or conflicting."""


@runtime_checkable
class AuditWriter(Protocol):
    """Persistence port for audit events.

    Implementations persist ``event`` durably and MUST raise on a persistence
    failure. They must not add a second catch/swallow hierarchy — the shared
    emission policy owns degradation, sanitized logging, and the strict versus
    best-effort decision.
    """

    def write(self, event: AuditEvent) -> None:
        """Persist a single audit event, raising on any persistence failure."""
        ...


_writer: AuditWriter | None = None


def bind_audit_writer(writer: AuditWriter) -> None:
    """Bind the process-wide audit writer.

    Idempotent for the same instance so a re-run of the startup hook is safe.
    Binding a *different* writer while one is already bound is a configuration
    error (fail closed), not a silent replacement.
    """
    global _writer
    if _writer is not None and _writer is not writer:
        raise AuditWriterBindingError("An audit writer is already bound to a different implementation")
    _writer = writer


def get_audit_writer() -> AuditWriter:
    """Return the bound audit writer, or raise if startup never bound one."""
    if _writer is None:
        raise AuditWriterBindingError("No audit writer bound; bind one at startup (config.apps.PortalConfig.ready)")
    return _writer


def reset_audit_writer() -> None:
    """Clear the binding. Test-only; production binds once at startup."""
    global _writer
    _writer = None
