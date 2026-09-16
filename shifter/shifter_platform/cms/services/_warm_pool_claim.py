"""CMS warm-pool claim path for initial launches (#28).

Inserted into the canonical RAES launch orchestration *after* every product,
tenancy, backend, and capacity gate and the reauthorized workspace lock, and
*before* the cold create branch. A miss, race, disabled policy, or unsupported
backend cold-falls-back with the inputs already validated for that launch -- no
divergent revalidation (preflight #28).

On a hit the claim is atomic (``engine.services.claim_ready_generation``), the
system-owned generation's ownership and workspace scope are transferred to the
claimant through the audited ``reassign_range_owner(..., rehome=True)`` facade
(the same handover the CTF spare path uses -- shared low-level mechanism, not the
CTF recovery policy), and only then is the durable ``activate`` operation enqueued.
The provisioner's activation rotates/scrubs every pre-claim credential and access
surface and creates the claimant's fresh access; nothing user-specific is reused.

Compatibility is decided by the canonical digest (:mod:`shared.warm_pool.compatibility`):
the launch computes the digest of its immutable inputs and claims a ready
generation whose digest is equal. The digest excludes ``user_id`` -- warm
eligibility is the ownership-neutral RAES realization identity (registered
``package_digest`` + ``lock_digest``, #1607).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.contrib.auth.models import User
from django.db import transaction

from shared.enums import RangeSource
from shared.range_instantiation_policy import InstantiationPurpose, backend_supports_warm_activation
from shared.warm_pool.compatibility import CompatibilityKey, compatibility_digest
from shared.warm_pool.policy import (
    WarmPoolBucketPolicy,
    WarmPoolOverride,
    WarmPoolRuntimePolicy,
    resolve_effective_policy,
)

if TYPE_CHECKING:
    from cms.models import RangeInstance
    from cms.services._range_lease import RangeLease

logger = logging.getLogger(__name__)

# Reconciler assumptions the warm-prepare side stamps its generations with; the
# launch side must derive the same values for a claim to match. Warm v1 serves
# personal-workspace Mission Control live-fire launches; any other launch computes
# a different digest and safely cold-falls-back.
ISOLATION_PERSONAL = "personal"
ISOLATION_SHARED = "shared"


def warm_isolation_class(user: User, workspace_id: int) -> str:
    """Classify the launch workspace for the compatibility digest: personal vs shared.

    Goes through the workspaces service seam (ADR-001): the launch workspace is
    personal iff it is the user's own personal workspace. Warm v1 prepares
    generations for the personal-workspace class, so a shared/org-workspace launch
    computes a different digest and cold-falls-back.
    """
    from workspaces.services import resolve_personal_workspace

    personal = resolve_personal_workspace(user)
    return ISOLATION_PERSONAL if personal.workspace_id == workspace_id else ISOLATION_SHARED


@dataclass(frozen=True)
class WarmClaimRequest:
    """Immutable launch inputs for one warm-pool claim attempt (#28).

    Groups the realization identity and launch context so the claim path derives
    the same compatibility digest the warm reconciler stamped, resolved
    independently on each side.
    """

    user: User
    scenario: str
    package_digest: str
    lock_digest: str
    backend: str
    instantiation_purpose: InstantiationPurpose
    range_source: RangeSource
    workspace_id: int
    egress_mode: str
    request_id: UUID
    #: Trusted event deadline for a CTF-owned generation. Mission Control policy is
    #: resolved only after a warm generation is claimed inside this transaction.
    enforced_deadline: datetime | None = None


@dataclass(frozen=True)
class _ClaimOutcome:
    """The result of a committed atomic claim, carried to the post-commit steps."""

    request_id: UUID
    bucket_id: str
    generation_uuid: UUID


def _eligible_buckets(policy: WarmPoolRuntimePolicy, *, backend: str, scenario: str) -> list[WarmPoolBucketPolicy]:
    """Return the effective-policy buckets that warm this backend+scenario.

    These are the only buckets a launch may claim from; an override that disables or
    narrows the bucket set removes candidates here, and the claim is filtered to
    exactly these bucket ids so a launch can never receive a generation from a
    bucket the current server-side (deployment + override) policy no longer
    authorizes (security: policy-to-allocation binding).
    """
    return [b for b in policy.buckets if b.backend == backend and b.scenario == scenario]


def _resolve_claim_candidates(request: WarmClaimRequest, override: WarmPoolOverride | None) -> list[tuple[str, str]]:
    """Return ``(bucket_id, digest)`` candidate pairs, or ``[]`` when warm is unavailable.

    Empty covers every not-attemptable branch (disabled/narrowed policy, a backend
    without a warm-activation adapter, or no eligible bucket) so the caller cold-
    falls-back on a single ``[]`` check.
    """
    from django.conf import settings

    policy: WarmPoolRuntimePolicy = resolve_effective_policy(settings.WARM_POOL_POLICY, override)
    if not policy.is_active() or not backend_supports_warm_activation(request.backend):
        # A bucket may target a backend without a warm-activation adapter; such a
        # generation can never be safely handed over, so never claim -- cold path.
        return []
    eligible = _eligible_buckets(policy, backend=request.backend, scenario=request.scenario)
    if not eligible:
        return []

    isolation = warm_isolation_class(request.user, request.workspace_id)
    # The digest is the launch's independently-resolved realization identity (same
    # for every eligible bucket of this scenario/backend). Authorization to a
    # specific bucket is the *separate* eligibility filter: candidates pair each
    # effective-policy bucket id with that digest, so the claim can only take a
    # generation whose realization matches AND whose bucket the current policy still
    # authorizes for this launch. No bucket-declared routing is echoed into the
    # digest; the bucket-set filter enforces policy-to-allocation binding.
    digest = compatibility_digest(
        CompatibilityKey(
            backend=request.backend,
            instantiation_purpose=request.instantiation_purpose.value,
            range_source=request.range_source.value,
            workspace_isolation_class=isolation,
            egress_mode=request.egress_mode,
            scenario=request.scenario,
            package_digest=request.package_digest,
            lock_digest=request.lock_digest,
        )
    )
    return [(bucket.id, digest) for bucket in eligible]


def _run_atomic_claim(request: WarmClaimRequest, candidates: list[tuple[str, str]]) -> _ClaimOutcome | None:
    """Claim + rehome one ready generation in a single transaction.

    Returns the committed outcome, or ``None`` on a genuine miss or a rollback of an
    inconsistent ledger row (both cold-fall-back). The claim and ownership transfer
    share one transaction so a transfer failure returns the generation to READY.
    """
    from cms.services import AuditEvent, audit_log
    from cms.services._range_reassign import reassign_range_owner
    from engine.services import claim_ready_generation
    from shared.audit.vocabulary import AuditAction, AuditActorType, AuditEntityType
    from shared.warm_pool.metrics import CLAIM_FALLBACK, emit_claim_outcome

    try:
        with transaction.atomic():
            generation = claim_ready_generation(
                candidates=candidates,
                backend=request.backend,
                range_source=request.range_source.value,
                claimant_request_id=request.request_id,
            )
            if generation is None:
                # Warm is enabled for this class but no compatible ready generation
                # in an authorized bucket was available: a genuine miss -> cold path.
                emit_claim_outcome(bucket_id="", backend=request.backend, outcome=CLAIM_FALLBACK)
                return None
            range_instance = _system_range_instance_for(generation.request_id)
            if range_instance is None:
                # A claimed generation with no CMS range instance is an inconsistent
                # ledger row; abort the claim (rolls back) and cold-fall-back rather
                # than hand over a half-modeled range.
                logger.error("warm claim: generation %s has no CMS range instance; rolling back", generation.uuid)
                raise _WarmClaimRollback
            reassign_range_owner(range_instance.pk, request.user, rehome=True)
            from cms.services._range_lease import build_range_lease, build_resolved_mission_control_range_lease

            lease = (
                build_resolved_mission_control_range_lease(request.user, for_update=True)
                if request.range_source is RangeSource.MISSION_CONTROL
                else build_range_lease(request.range_source, enforced_deadline=request.enforced_deadline)
            )
            _assign_initial_user_lease(range_instance, lease)
            audit_log(
                AuditEvent(
                    entity_type=AuditEntityType.RANGE.value,
                    entity_id=range_instance.pk,
                    action=AuditAction.WARM_CLAIM.value,
                    actor_type=AuditActorType.USER.value,
                    actor_id=request.user.id,
                    new_state={
                        "bucket": generation.bucket_id,
                        "generation": str(generation.uuid),
                        "claimed_request_id": str(generation.request_id),
                        "range_source": request.range_source.value,
                    },
                    request_id=str(generation.request_id),
                )
            )
            outcome = _ClaimOutcome(
                request_id=generation.request_id,
                bucket_id=generation.bucket_id,
                generation_uuid=generation.uuid,
            )
    except _WarmClaimRollback:
        return None
    return outcome


def attempt_warm_claim(request: WarmClaimRequest, override: WarmPoolOverride | None = None) -> UUID | None:
    """Attempt to claim a compatible ready warm generation for this launch.

    Returns the claimed generation's Engine ``request_id`` on a hit (the launch
    binds its result to that realized generation), or ``None`` to cold-fall-back.
    Never raises for a miss; a miss is a normal branch.
    """
    from engine.services import enqueue_range_activation
    from shared.warm_pool.metrics import CLAIM_HIT, emit_claim_outcome

    candidates = _resolve_claim_candidates(request, override)
    if not candidates:
        return None
    outcome = _run_atomic_claim(request, candidates)
    if outcome is None:
        return None
    enqueue_range_activation(outcome.request_id)
    emit_claim_outcome(bucket_id=outcome.bucket_id, backend=request.backend, outcome=CLAIM_HIT)
    logger.info(
        "warm claim: hit bucket=%s generation=%s user_id=%s",
        outcome.bucket_id,
        outcome.generation_uuid,
        request.user.id,
    )
    return outcome.request_id


class _WarmClaimRollback(Exception):
    """Internal sentinel to roll back an inconsistent claim to cold fallback."""


def _system_range_instance_for(request_id: UUID) -> RangeInstance | None:
    """Return the system-owned CMS RangeInstance correlated to ``request_id``."""
    from cms.models import RangeInstance

    return RangeInstance.objects.filter(request__request_id=request_id).select_related("request").first()


def _assign_initial_user_lease(range_instance: RangeInstance, lease: RangeLease) -> None:
    """First-assign the claimant's user lease onto an unleased warm generation (#27).

    A warm-prepared generation is system-owned and unleased, so the user lifetime
    starts at this claim -- persisting the deadline (the sole automatic-cleanup
    authority) and the generation's extension increment inside the same claim/ownership
    transaction, before activation. Guard on an unleased row (``maximum_expires_at is
    None``) so rehoming never resets an already-leased generation's ceiling (e.g. a CTF
    spare keeps its event deadline). The separate warm idle ledger continues to own
    pre-claim pool cost and retirement.
    """
    if range_instance.maximum_expires_at is not None:
        return
    range_instance.expires_at = lease.expires_at
    range_instance.maximum_expires_at = lease.maximum_expires_at
    range_instance.extension_days = lease.extension_days
    range_instance.lease_initial_days = lease.initial_days
    range_instance.lease_maximum_days = lease.maximum_days
    range_instance.lease_policy_source = lease.policy_source
    range_instance.lease_policy_tenant_revision = lease.tenant_revision
    range_instance.lease_policy_group_revisions = [
        {"group_id": group_id, "revision": revision} for group_id, revision in lease.group_revisions
    ]
    range_instance.save(
        update_fields=[
            "expires_at",
            "maximum_expires_at",
            "extension_days",
            "lease_initial_days",
            "lease_maximum_days",
            "lease_policy_source",
            "lease_policy_tenant_revision",
            "lease_policy_group_revisions",
            "updated_at",
        ]
    )
