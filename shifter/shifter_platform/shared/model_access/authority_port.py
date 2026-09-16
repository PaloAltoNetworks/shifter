"""Neutral synchronous sharing-authority invalidation port (PLAT-202 M20).

Identity and workspace owners cannot depend on Engine.  They emit one closed,
bounded command through this process-wide port while their owner transaction is
open; the composition root binds Engine's small fence writer once at startup.
Missing or conflicting bindings fail closed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from shared.model_access.authority import AuthorityInvalidation

AuthorityInvalidator = Callable[[AuthorityInvalidation], int]


class AuthorityInvalidatorBindingError(RuntimeError):
    """Raised when the authority invalidator binding is missing or conflicting."""


_invalidator: AuthorityInvalidator | None = None
_signal_guard = threading.local()


def bind_authority_invalidator(invalidator: AuthorityInvalidator) -> None:
    """Bind one writer; rebinding the same callable is idempotent."""
    global _invalidator
    if _invalidator is not None and _invalidator is not invalidator:
        raise AuthorityInvalidatorBindingError(
            "A sharing authority invalidator is already bound to a different implementation"
        )
    _invalidator = invalidator


def invalidate_authority(command: AuthorityInvalidation) -> int:
    """Synchronously persist an owner invalidation or deny when startup did not bind it."""
    if _invalidator is None:
        raise AuthorityInvalidatorBindingError(
            "No sharing authority invalidator bound; bind one at startup (config.apps.PortalConfig.ready)"
        )
    return _invalidator(command)


def reset_authority_invalidator() -> None:
    """Clear the binding. Test-only; production binds once at startup."""
    global _invalidator
    _invalidator = None


@contextmanager
def suppress_authority_invalidation_signals() -> Iterator[None]:
    """Let an owner service replace defense-in-depth signals with its atomic command."""
    prior = getattr(_signal_guard, "depth", 0)
    _signal_guard.depth = prior + 1
    try:
        yield
    finally:
        _signal_guard.depth = prior


def authority_invalidation_signals_suppressed() -> bool:
    """Whether the current thread is inside an authoritative owner mutation."""
    return bool(getattr(_signal_guard, "depth", 0))
