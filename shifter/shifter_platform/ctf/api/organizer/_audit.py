"""Platform-admin override audit helpers for the CTF organizer API (ADR-052).

The DRF organizer resolvers capture the admitting authority on the request
(:func:`ctf.api.organizer._base._capture_event_authority`); these helpers consume
that capture to write the mandatory ``shared.audit`` record whenever a mutation
actually uses the platform-admin override. Database-only mutations audit
atomically inside the mutation transaction; non-rollbackable external workflows
record bounded intent before their first side effect and a correlated outcome.

Kept in a dedicated module (rather than ``_base``) so neither file exceeds the
file-size budget. ``_actor`` and the shared audit writer are imported lazily so
this module carries no import-time dependency on ``_base`` or the service layer.
"""

from __future__ import annotations

import contextlib
import functools
from typing import TYPE_CHECKING, Any

from rest_framework.request import Request

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from rest_framework.response import Response
    from rest_framework.views import APIView

    from ctf.models import CTFEvent
    from ctf.services.authorization import EventAuthoritySource


def _audit_admin_from_request(
    request: Request,
    operation: str,
    *,
    action: str | None = None,
    changed_fields: list[str] | None = None,
    outcome: str | None = None,
) -> None:
    """Audit a mutation using the authority captured by the request's resolver.

    No-op when nothing was captured or the authority was owner/delegated-staff;
    writes the strict override audit only for a platform-admin mutation. Callers
    that mutate the database wrap the service call plus this helper in one
    transaction so a strict audit failure rolls the mutation back (ADR-052-R4).
    """
    captured = getattr(request, "_ctf_admin_authority", None)
    if captured is None:
        return
    event, source = captured
    _audit_admin_mutation(
        request, event, source, operation, action=action, changed_fields=changed_fields, outcome=outcome
    )


def _audit_admin_mutation(
    request: Request,
    event: CTFEvent,
    source: EventAuthoritySource | None,
    operation: str,
    *,
    action: str | None = None,
    changed_fields: list[str] | None = None,
    outcome: str | None = None,
) -> None:
    """Strict-audit a mutation only when it used the platform-admin override (ADR-052-R4).

    No-op for owner or delegated-staff authority. ``action`` defaults to the
    audit ``UPDATE`` verb; pass an explicit verb (e.g. ``DELETE``) where the
    operation differs. Database-only callers wrap the mutation plus this call in
    one transaction; a non-rollbackable caller records ``outcome="intent"`` before
    its first side effect and a correlated outcome afterward.
    """
    from ctf.api.organizer._base import _actor
    from ctf.services.audit import audit_platform_admin_event_action
    from ctf.services.authorization import EventAuthoritySource

    if source is not EventAuthoritySource.PLATFORM_ADMIN:
        return
    kwargs: dict[str, Any] = {} if action is None else {"action": action}
    audit_platform_admin_event_action(
        request=request,
        event=event,
        operation=operation,
        effective_actor_id=_actor(request).pk,
        changed_fields=changed_fields,
        outcome=outcome,
        **kwargs,
    )


def audit_admin_event_mutation(operation: str, *, action: str | None = None) -> Callable[..., Any]:
    """Decorate a **database-only** organizer mutation to audit a platform-admin override.

    The method resolves its event-derived target through the shared resolvers,
    which capture the admitting authority on the request; this decorator runs the
    method and the strict override audit inside one transaction, so a strict audit
    failure rolls the mutation back on a successful (2xx) response (ADR-052-R4). It
    is a no-op for owner or delegated-staff authority and for non-success
    responses.

    Non-rollbackable workflows (uploads, notifications, participant provisioning,
    content, ranges) must NOT use this decorator: holding a transaction across an
    external side effect is unsafe, and a completion-only record cannot satisfy
    the intent-before-side-effect requirement. Those endpoints wrap their side
    effect in :func:`admin_external_audit` instead.
    """

    def decorator(method: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap ``method`` so a successful platform-admin mutation is audited in-transaction."""

        @functools.wraps(method)
        def wrapper(self: APIView, request: Request, *args: Any, **kwargs: Any) -> Response:
            """Run the mutation and its override audit inside one transaction."""
            from django.db import transaction

            with transaction.atomic():
                response = method(self, request, *args, **kwargs)
                if 200 <= getattr(response, "status_code", 500) < 300:
                    _audit_admin_from_request(request, operation, action=action)
                return response

        return wrapper

    return decorator


@contextlib.contextmanager
def admin_external_audit(request: Request, operation: str, *, action: str | None = None) -> Iterator[None]:
    """Intent-before / outcome-after audit for a non-rollbackable platform-admin mutation.

    The caller must have already resolved the event authority (captured on the
    request) before entering this context. On enter it strictly persists a bounded
    ``intent`` record before the wrapped side effect; on exit it persists a
    correlated ``completed`` or ``failed`` outcome. Every record is a no-op unless
    the resolved authority is the platform-admin override, and no database
    transaction is held across the side effect (ADR-052-R4). ``failed`` carries
    only the bounded operation identifiers — never raw exception text.
    """
    _audit_admin_from_request(request, operation, action=action, outcome="intent")
    try:
        yield
    except BaseException:
        _audit_admin_from_request(request, operation, action=action, outcome="failed")
        raise
    else:
        _audit_admin_from_request(request, operation, action=action, outcome="completed")
