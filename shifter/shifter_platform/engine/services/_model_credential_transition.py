"""One-use guest refresh across an explicitly admitted model-policy successor."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from shared.model_access.credentials import ModelTokenPair

if TYPE_CHECKING:
    from engine.models import ModelAccessCredential, ModelAllocation

from shared.model_access import ContractError
from shared.model_access.network import peer_matches_binding

CREDENTIAL_UNAVAILABLE = "credential.unavailable"


def refresh_successor(token: str, peer: str, moment: datetime) -> ModelTokenPair | None:
    """Never revive a revoked grant; consume its proof only for a linked successor."""
    from engine.models import ModelAccessCredential, Range
    from engine.services._model_credentials import _lock_binding, _parse_token, _rotate, _trusted_subnets

    public_id = _parse_token(token)
    initial = ModelAccessCredential.objects.select_related("grant__allocation").filter(grant_id=public_id).first()
    if initial is None or initial.replacement_grant_id is None:
        return None
    prior = initial.grant.allocation
    range_obj = Range.objects.select_for_update().get(uuid=prior.range_id)
    old = ModelAccessCredential.objects.select_for_update().select_related("grant__allocation").get(pk=initial.pk)
    _validate_refresh_proof(old, token, moment)
    candidate = _successor(old.replacement_grant_id, prior)
    allocation, grant, current_range = _lock_binding(candidate.pk, moment)
    if (
        allocation.source_policy_revision != range_obj.model_source_policy_revision
        or grant.state != "pending"
        or ModelAccessCredential.objects.filter(grant=grant).exists()
    ):
        raise ContractError(CREDENTIAL_UNAVAILABLE)
    subnets = _trusted_subnets(current_range, allocation)
    if subnets != old.admitted_subnets or not any(peer_matches_binding(peer, subnet) for subnet in subnets):
        raise ContractError(CREDENTIAL_UNAVAILABLE)
    credential = ModelAccessCredential.objects.create(
        grant=grant,
        grant_epoch=grant.grant_epoch,
        admitted_subnets=subnets,
        enrollment_expires_at=moment,
        hard_expires_at=min(old.hard_expires_at, allocation.deadline),
        rotation_window_started_at=old.rotation_window_started_at,
        rotation_count=old.rotation_count,
    )
    old.refresh_hash = old.access_hash = old.enrollment_hash = ""
    old.save(update_fields=["refresh_hash", "access_hash", "enrollment_hash", "updated_at"])
    grant.state = "active"
    grant.save(update_fields=["state"])
    return _rotate(grant, credential, moment)


def _successor(successor_id: UUID | None, prior: ModelAllocation) -> ModelAllocation:
    """Follow at most 32 server-written successor links within one workload owner."""
    from engine.models import ModelAccessCredential, ModelPendingGrant

    # Only a server-written successor link crosses the revocation boundary.
    # Several admin edits before a guest refresh can form a bounded chain.
    visited = set()
    for _ in range(32):
        if successor_id is None or successor_id in visited:
            raise ContractError(CREDENTIAL_UNAVAILABLE)
        visited.add(successor_id)
        grant = ModelPendingGrant.objects.select_related("allocation").get(pk=successor_id)
        candidate = grant.allocation
        _validate_successor(candidate, prior)
        if grant.state != "revoked":
            break
        successor_id = (
            ModelAccessCredential.objects.filter(grant=grant).values_list("replacement_grant_id", flat=True).first()
        )
    else:
        raise ContractError(CREDENTIAL_UNAVAILABLE)
    return candidate


def _validate_successor(candidate: ModelAllocation, prior: ModelAllocation) -> None:
    """A refresh link must advance policy without crossing execution or ownership."""
    if (
        candidate.range_id != prior.range_id
        or candidate.operation_id != prior.operation_id
        or candidate.workload_role != prior.workload_role
        or candidate.source_policy_revision <= prior.source_policy_revision
        or candidate.snapshot["request"]["owner_ref"] != prior.snapshot["request"]["owner_ref"]
    ):
        raise ContractError(CREDENTIAL_UNAVAILABLE)


def _validate_refresh_proof(old: ModelAccessCredential, token: str, moment: datetime) -> None:
    """Require an unexpired, unconsumed proof on the revoked predecessor."""
    from engine.services._model_credentials import _hash

    if (
        old.hard_expires_at <= moment
        or not old.refresh_hash
        or not secrets.compare_digest(old.refresh_hash, _hash(token))
        or old.grant.state != "revoked"
    ):
        raise ContractError(CREDENTIAL_UNAVAILABLE)
