"""Mission Control Guacamole remote-access session application service.

One transport-neutral use-case entry point, :func:`launch_guacamole_session`,
owns the Guacamole browser-session orchestration that the DRF views used to
perform inline (issue #991). Given the authenticated actor, a closed access
kind (:class:`~mission_control.models.GuacamoleBootstrapRequest.Protocol`), and
an opaque target identifier, it:

1. binds the Guacamole runtime configuration (signing secret + base/API URLs);
2. enqueues the existing bounded asynchronous bootstrap (#929) so credential
   resolution and the Guacamole token exchange run off the request thread; and
3. inside that worker, per the access kind, resolves the sanctioned public
   ``engine.services`` connection projection, adapts it into the existing
   ``mission_control.guacamole`` request dataclass, and calls the existing
   Guacamole broker. The existing bootstrap lifecycle persists and delivers the
   resulting URL.

The per-protocol resolve-and-mint building blocks live in
:mod:`mission_control._guacamole_session_builders` (split for Sonar S104's
500-line cap); this module keeps the HTTP-neutral entry point, the closed
access-kind dispatch, and the enqueue glue.

The service is HTTP-neutral: it never builds a ``JsonResponse``, reverses a
URL, or re-parses a response body. Synchronous configuration/readiness failures
and worker-side orchestration failures both surface as
:class:`~mission_control.guacamole_bootstrap.BootstrapFailure` (a safe message
plus an HTTP status code) -- the DRF adapter renders the former and the
bootstrap worker persists the latter, so there is no separate exception
hierarchy. This keeps each view a thin HTTP adapter (authenticate, validate,
one service call, render) while consuming only the ADR-001-R4 allowlisted
``engine.services`` symbols.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from mission_control._guacamole_session_builders import (
    _build_ngfw_ssh_url,
    _build_range_ssh_url,
    _build_rdp_url,
)
from mission_control.guacamole_bootstrap import BootstrapFailure, BootstrapQueueFull, enqueue_guacamole_bootstrap
from mission_control.models import GuacamoleBootstrapRequest
from shared.log_sanitize import safe_log_fingerprint, safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from mission_control.guacamole import GuacamoleClient

logger = logging.getLogger(__name__)

_GUAC_AUTH_NOT_CONFIGURED = "Guacamole JSON auth is not configured"
_GUACAMOLE_BASE_PATH = "/guacamole"


def _bind_guacamole_client(service_name: str) -> GuacamoleClient:
    """Bind Guacamole runtime configuration into a client, or raise a 503.

    Runs synchronously on the request thread so a missing signing secret fails
    closed before any bootstrap is enqueued (matching the prior view behaviour).
    Reads the existing ``GUACAMOLE_*`` settings once at this application-service
    edge; the client and its retry loop never read Django settings (issue #993).
    """
    from django.conf import settings

    from mission_control.guacamole import GuacamoleClientConfig, get_guacamole_client

    signing_secret = getattr(settings, "GUACAMOLE_JSON_AUTH_SECRET", "")
    if not signing_secret:
        logger.error(_GUAC_AUTH_NOT_CONFIGURED)
        raise BootstrapFailure(f"{service_name} service not configured", status_code=503)
    config = GuacamoleClientConfig(
        base_url=getattr(settings, "GUACAMOLE_BASE_URL", _GUACAMOLE_BASE_PATH),
        secret_key=signing_secret,
        api_base_url=getattr(settings, "GUACAMOLE_API_BASE_URL", None),
        retry_attempts=getattr(settings, "GUACAMOLE_TOKEN_RETRY_ATTEMPTS", 3),
        retry_base_delay_ms=getattr(settings, "GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS", 200),
    )
    return get_guacamole_client(config)


@dataclass(frozen=True)
class GuacamoleSessionLaunch:
    """HTTP-neutral result of enqueuing a Guacamole bootstrap.

    Carries only the enqueued bootstrap facts the launch adapter needs to render
    the 202 response. The final bearer URL is never returned here; it remains
    available only from the owner-scoped, single-consume status endpoint.
    """

    bootstrap_id: UUID
    status: str


def _service_name(protocol: str) -> str:
    """Return the user-facing service label for the not-configured message."""
    return "RDP" if protocol == GuacamoleBootstrapRequest.Protocol.RDP else "SSH"


def _actor_user_id(user: User) -> int:
    """Return the authenticated user's integer id or raise a neutral failure."""
    for attr in ("pk", "id"):
        value = getattr(user, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    raise BootstrapFailure("Authenticated user id unavailable", status_code=500)


def _worker_build_callable(
    *,
    protocol: str,
    user: User,
    target_id: str,
    guac_client: GuacamoleClient,
) -> Callable[[], str]:
    """Return the closed-access-kind worker callable that builds the signed URL.

    The dispatch keeps range SSH and NGFW SSH distinct (they share the Guacamole
    SSH transport but not their ownership/connection-name policy). Adding a new
    browser-session kind adds one branch here plus its resolver/adapter, reusing
    the same bootstrap, delivery, client, error, and logging envelopes.
    """
    protocols = GuacamoleBootstrapRequest.Protocol
    if protocol == protocols.RDP:
        return lambda: _build_rdp_url(user=user, instance_uuid=target_id, guac_client=guac_client)
    if protocol == protocols.RANGE_SSH:
        return lambda: _build_range_ssh_url(user=user, instance_uuid=target_id, guac_client=guac_client)
    if protocol == protocols.NGFW_SSH:
        return lambda: _build_ngfw_ssh_url(user=user, app_id=target_id, guac_client=guac_client)
    raise ValueError(f"Unsupported Guacamole access kind: {protocol!r}")


def launch_guacamole_session(
    *,
    user: User,
    protocol: str,
    target_id: str,
    guacamole_client: GuacamoleClient | None = None,
) -> GuacamoleSessionLaunch:
    """Launch a Guacamole browser session for ``user`` against ``target_id``.

    Binds Guacamole configuration into a client (or uses the injected
    ``guacamole_client`` — the explicit, keyword-only test seam, issue #993),
    enqueues the bounded async bootstrap (#929), and returns the HTTP-neutral
    :class:`GuacamoleSessionLaunch`. Raises
    :class:`~mission_control.guacamole_bootstrap.BootstrapFailure` for a
    synchronous readiness/config failure (e.g. missing signing secret -> 503)
    and :class:`~mission_control.guacamole_bootstrap.BootstrapQueueFull` when
    the worker pool is saturated; the launch adapter renders both. Worker-side
    resolution/generation failures are persisted on the bootstrap row and
    surfaced by the status endpoint, not raised here.
    """
    guac_client = guacamole_client or _bind_guacamole_client(_service_name(protocol))
    if protocol == GuacamoleBootstrapRequest.Protocol.NGFW_SSH:
        logger.info(
            "Guacamole SSH bootstrap queued for NGFW: user=%s ngfw_uuid=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(target_id),
        )
    build_url = _worker_build_callable(
        protocol=protocol,
        user=user,
        target_id=target_id,
        guac_client=guac_client,
    )
    try:
        bootstrap = enqueue_guacamole_bootstrap(
            user_id=_actor_user_id(user),
            protocol=protocol,
            target_id=target_id,
            build_url=build_url,
        )
    except BootstrapQueueFull:
        # Preserve the application-level saturation signal (the adapter maps this
        # to a 503 + Retry-After). Only non-secret kind/target/user identifiers.
        logger.warning(
            "Guacamole bootstrap worker capacity exhausted: user=%s protocol=%s target_id=%s",
            safe_log_fingerprint(user.email),
            safe_log_value(protocol),
            safe_log_value(target_id),
        )
        raise
    return GuacamoleSessionLaunch(bootstrap_id=bootstrap.id, status=bootstrap.status)
