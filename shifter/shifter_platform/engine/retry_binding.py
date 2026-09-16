"""Bind a caller retry key to one server-owned range operation (#2086, ADR-063).

First use mints the operation and records the binding atomically; a replay with
the same immutable intent recovers the original operation without new effects; a
replay with a *different* intent conflicts before any reservation or effect. When
two callers race the same key, PostgreSQL uniqueness picks one winner and the
loser's whole transaction -- including its reservations -- rolls back, so
same-key contenders converge on exactly one binding and one set of effects
(ADR-063-R3). The insertion race is resolved outside the failed savepoint before
reading the winner.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.utils import timezone

from shared.exceptions import ValidationError

if TYPE_CHECKING:
    from engine.models import PublicOperationRetryBinding

__all__ = [
    "DEFAULT_RETRY_TTL_SECONDS",
    "MintedOperation",
    "RetryBindingResult",
    "RetryKeyConflict",
    "bind_public_operation",
    "lookup_public_operation",
    "prune_expired_retry_bindings",
]

# Advertised retry window. A binding (later a tombstone) is retained at least this
# long so a delayed lost-response replay recovers the original operation rather
# than minting a duplicate (ADR-063-R2). Retention pruning must never delete the
# sole binding for an unresolved operation (ADR-063-R5).
DEFAULT_RETRY_TTL_SECONDS = 7 * 24 * 3600


class RetryKeyConflict(ValidationError):
    """Same retry key, different immutable intent -- fail closed before effects (ADR-063-R2)."""


@dataclass(frozen=True)
class MintedOperation:
    """The server-owned identity produced by first use of a retry key.

    ``operation_id`` is the operation generation when it is already minted at bind
    time; it may be ``None`` when the generation is minted asynchronously after the
    request is created, in which case the current generation is resolved from the
    request when needed (ADR-063-R1).
    """

    request_id: str
    operation_id: str | None = None


@dataclass(frozen=True)
class RetryBindingResult:
    """Outcome of resolving a retry key.

    ``created`` is True only for the caller that drove first use (it owns the
    dispatched effects); a recovered replay returns False and the same operation.
    """

    binding: PublicOperationRetryBinding
    created: bool


def _resolved(binding: PublicOperationRetryBinding, intent_digest: str) -> RetryBindingResult:
    """Recover a matching binding, or conflict when the bound intent differs."""
    if binding.intent_digest != intent_digest:
        raise RetryKeyConflict("retry key is already bound to a different operation intent")
    return RetryBindingResult(binding=binding, created=False)


def lookup_public_operation(
    *, deployment_scope: str, actor_key: str, action: str, caller_key: str
) -> PublicOperationRetryBinding | None:
    """Return the binding for a retry identity, or ``None`` when unbound."""
    from engine.models import PublicOperationRetryBinding

    return PublicOperationRetryBinding.objects.filter(
        deployment_scope=deployment_scope,
        actor_key=actor_key,
        action=action,
        caller_key=caller_key,
    ).first()


def bind_public_operation(
    *,
    deployment_scope: str,
    actor_key: str,
    action: str,
    caller_key: str,
    intent_digest: str,
    mint: Callable[[], MintedOperation],
    ttl_seconds: int = DEFAULT_RETRY_TTL_SECONDS,
) -> RetryBindingResult:
    """Recover an existing binding, else mint + bind on first use.

    ``mint`` is invoked only on first use, inside the binding transaction, and
    returns a :class:`MintedOperation`. If a concurrent contender wins the unique
    key, this transaction (including everything ``mint`` reserved) rolls back on
    ``IntegrityError``; the winner is then read outside the failed transaction and
    recovered (or conflicts). The binding records ``INTENT_PROJECTION_VERSION`` --
    the version ``intent_digest`` was computed under.
    """
    from engine.models import PublicOperationRetryBinding, RetryBindingStatus
    from shared.operation_intent import INTENT_PROJECTION_VERSION

    key = {
        "deployment_scope": deployment_scope,
        "actor_key": actor_key,
        "action": action,
        "caller_key": caller_key,
    }
    existing = lookup_public_operation(**key)
    if existing is not None:
        return _resolved(existing, intent_digest)
    try:
        with transaction.atomic():
            minted = mint()
            binding = PublicOperationRetryBinding.objects.create(
                **key,
                request_id=minted.request_id,
                operation_id=minted.operation_id,
                intent_digest=intent_digest,
                intent_projection_version=INTENT_PROJECTION_VERSION,
                status=RetryBindingStatus.ACTIVE,
                expires_at=timezone.now() + timedelta(seconds=ttl_seconds),
            )
        return RetryBindingResult(binding=binding, created=True)
    except IntegrityError:
        # A concurrent contender won the key; our reservations rolled back with the
        # transaction. Read the committed winner outside the failed savepoint.
        pass
    winner = PublicOperationRetryBinding.objects.get(**key)
    return _resolved(winner, intent_digest)


def prune_expired_retry_bindings(*, batch_size: int) -> int:
    """Delete retry bindings past retention, never the sole evidence of an unresolved operation.

    A binding is prunable only when its retention window has elapsed AND the bound
    operation's cleanup is verified absent by durable scoped provider
    inventory/readback evidence (ADR-063-R4/R5). A logical ``DESTROYED`` status, a
    missing Range, a timeout, DLQ, or ``FAILED`` is never treated as proof of
    absence, so those bindings (the recovery / residual evidence) are retained
    until inventory confirms every owned resource is gone.
    """
    from engine.models import PublicOperationRetryBinding

    from .services._cleanup_verification import is_cleanup_verified_absent

    limit = max(1, int(batch_size))
    candidates = list(
        PublicOperationRetryBinding.objects.filter(expires_at__lte=timezone.now()).order_by("expires_at")[:limit]
    )
    prunable: list[int] = []
    for binding in candidates:
        if is_cleanup_verified_absent(binding.request_id):
            prunable.append(binding.pk)
    if not prunable:
        return 0
    deleted, _details = PublicOperationRetryBinding.objects.filter(pk__in=prunable).delete()
    return deleted
