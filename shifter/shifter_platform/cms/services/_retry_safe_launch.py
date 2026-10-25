"""Retry-safe range launch: bind a caller retry key to one launch operation.

#2086, ADR-063. A public caller supplies a retry key so a lost launch response can
be recovered without a duplicate launch. Recovery is looked up and projected from
the *bound* request/operation (never the caller's current active range) and does
not recompile or re-validate the caller's original selections against today's
catalog, so a replay recovers even after the scenario or agent is retired. First
use dispatches the normal RAES create path and binds the key to the resulting
request/operation generation and the caller's normalized intent; a replay with a
different caller intent conflicts before any effect (``RetryKeyConflict`` -> 409).

The digest covers only the caller-controlled selections (action, actor, workspace,
scenario, agent selection); the compiled-plan half of the immutable-intent binding
is enforced by the engine's ``OperationInput`` and its re-enqueue comparison.

This orchestration lives in the CMS layer because it owns ``create_range_dispatch``;
it reaches the retry-binding primitives only through the ``engine.services`` facade
(ADR-001).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.contrib.auth.models import User

from engine.services import (
    MintedOperation,
    bind_public_operation,
    lookup_public_operation,
    operation_id_for_request,
)
from shared.deployment import resolve_deployment_scope
from shared.operation_intent import INTENT_PROJECTION_VERSION, canonical_intent_digest

from ._raes_range_create import create_range_dispatch

__all__ = [
    "RetryKeyConflict",
    "RetrySafeLaunchOutcome",
    "bind_first_use_launch",
    "resolve_retry_recovery",
]

# Re-exported so callers in the same layer catch the conflict without reaching
# into engine.services directly.
from engine.services import RetryKeyConflict as RetryKeyConflict

# RAES packages own topology, so a launch operation is always a RAES provision.
_LAUNCH_ACTION = "raes-range:provision"


@dataclass(frozen=True)
class RetrySafeLaunchOutcome:
    """Result of a retry-safe launch.

    ``created`` is True for the caller that drove first use (a launch was
    dispatched); a recovered replay returns False and the same request/operation.
    """

    request_id: str
    operation_id: str
    created: bool


def _caller_intent(
    user: User,
    scenario: str,
    agents_selection: dict[str, Any],
    workspace_uuid: str | UUID | None,
    deployment_scope: str,
    model_sources: dict | None = None,
) -> dict[str, Any]:
    """Normalize the caller-controlled launch selections for the retry digest.

    Only inputs the caller controls belong here so a replay compares against the
    stored caller intent without recompiling or re-validating against the current
    catalog (ADR-063-R2). ``agents_selection`` is the raw normalized selection, not
    the catalog-resolved agent map, so recovery never depends on catalog lookups.
    """
    intent = {
        "intent_projection_version": INTENT_PROJECTION_VERSION,
        "deployment_scope": deployment_scope,
        "action": _LAUNCH_ACTION,
        "actor_key": str(user.id),
        "workspace_uuid": str(workspace_uuid) if workspace_uuid else None,
        "scenario": str(scenario),
        "agents_selection": agents_selection,
    }
    from shared.model_access.sources import ModelSourceSelection

    sources = ModelSourceSelection.model_validate(model_sources or {})
    if sources.aliases:
        intent["model_sources"] = sources.model_dump(mode="json")
    return intent


def _digest(
    user: User,
    scenario: str,
    agents_selection: dict[str, Any],
    workspace_uuid: str | UUID | None,
    deployment_scope: str,
    model_sources: dict | None = None,
) -> str:
    """Return the canonical digest of the caller's normalized launch intent."""
    return canonical_intent_digest(
        _caller_intent(user, scenario, agents_selection, workspace_uuid, deployment_scope, model_sources)
    )


def resolve_retry_recovery(
    user: User,
    *,
    scenario: str,
    agents_selection: dict[str, Any],
    workspace_uuid: str | UUID | None,
    caller_key: str,
    model_sources: dict | None = None,
) -> RetrySafeLaunchOutcome | None:
    """Recover a bound operation for a replay, without minting or re-validating.

    Returns the recovered outcome when the key is already bound to the same caller
    intent, ``None`` when the key is unbound (first use), and raises
    :class:`RetryKeyConflict` when the key is bound to a different intent. No
    catalog validation or effect occurs, so a retired scenario/agent still recovers.
    """
    deployment_scope = resolve_deployment_scope()
    digest = _digest(user, scenario, agents_selection, workspace_uuid, deployment_scope, model_sources)
    binding = lookup_public_operation(
        deployment_scope=deployment_scope,
        actor_key=str(user.id),
        action=_LAUNCH_ACTION,
        caller_key=caller_key,
    )
    if binding is None:
        return None
    if binding.intent_digest != digest:
        raise RetryKeyConflict("retry key is already bound to a different operation intent")
    return RetrySafeLaunchOutcome(
        request_id=str(binding.request_id),
        operation_id=str(binding.operation_id) if binding.operation_id else "",
        created=False,
    )


def bind_first_use_launch(
    user: User,
    *,
    scenario: str,
    agents_selection: dict[str, Any],
    agents_by_os: dict[str, int] | None,
    workspace_uuid: str | UUID | None = None,
    caller_key: str,
    model_sources: dict | None = None,
) -> RetrySafeLaunchOutcome:
    """Dispatch and bind on first use of a retry key (mint + bind atomically).

    A concurrent contender that wins the key rolls this transaction back and its
    outcome is recovered instead (or conflicts). The bound generation is persisted
    at bind time from the minted operation; it is never re-derived from the range's
    current generation on read.
    """
    deployment_scope = resolve_deployment_scope()
    digest = _digest(user, scenario, agents_selection, workspace_uuid, deployment_scope, model_sources)

    # RAES packages own topology; agents_by_os is accepted for caller back-compat
    # (the retry-key intent digest already binds agents_selection) but does not
    # shape the create_range_dispatch plan after PLAT-202 dropped that parameter
    # from the service seam. Matches ctf.bridges.cms_launch_range.
    del agents_by_os

    source_kwargs: dict[str, Any] = {"model_sources": model_sources} if model_sources else {}

    def mint() -> MintedOperation:
        """Dispatch the RAES create and return the minted request/operation identity."""
        ctx = create_range_dispatch(user, scenario, workspace_uuid=workspace_uuid, **source_kwargs)
        return MintedOperation(request_id=str(ctx.request_id), operation_id=operation_id_for_request(ctx.request_id))

    result = bind_public_operation(
        deployment_scope=deployment_scope,
        actor_key=str(user.id),
        action=_LAUNCH_ACTION,
        caller_key=caller_key,
        intent_digest=digest,
        mint=mint,
    )
    return RetrySafeLaunchOutcome(
        request_id=str(result.binding.request_id),
        operation_id=str(result.binding.operation_id) if result.binding.operation_id else "",
        created=result.created,
    )
