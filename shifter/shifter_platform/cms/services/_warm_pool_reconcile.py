"""Warm-pool reconciler: converge the pool toward its declared policy (#28).

Deployment-owned, provider-neutral. Each pass, for every bucket in the effective
deployment policy, it:

- **finalizes** retiring generations whose range destroy has been observed,
  releasing their held capacity only then (never at claim or destroy-request time);
- **retires** ready generations whose warm-idle deadline passed or whose
  compatibility digest no longer matches the bucket's current realization identity
  (a scenario/image/config change), through the canonical destroy lifecycle; and
- **replenishes** a shortfall by warm-preparing new system-owned, quarantined
  generations up to the bucket target, bounded by the bucket maximum, the
  deployment total-ready ceiling, and the per-pass concurrency.

The ledger is an Engine-owned model, so every generation query/mutation goes
through the ``engine.services`` seam (ADR-001); this module owns only the CMS
reservation + RAES warm-prepare dispatch that the Engine cannot perform, plus the
policy-driven decisions. A warm generation is a system-owned RAES range reserved
under a managed, inactive warm-pool user; its ledger row is created at reservation
time so the provision suppresses participant access (quarantine). No provider I/O
happens in a transaction: provision and destroy travel through durable RAES intents.

The reconciler prepares for the v1 warm target class (personal-workspace Mission
Control live-fire launches) and builds its compatibility digest from the same
:class:`shared.warm_pool.compatibility.CompatibilityKey` dimensions the launch
claim path uses, so a generation it prepares is claimable by exactly those launches.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from cms.services._warm_pool_claim import ISOLATION_PERSONAL
from shared.enums import RangeSource, ResourceStatus
from shared.operation_envelope import canonical_payload_digest
from shared.range_instantiation_policy import InstantiationPurpose, backend_supports_warm_activation
from shared.warm_pool.compatibility import CompatibilityKey, compatibility_digest
from shared.warm_pool.policy import WarmPoolBucketPolicy, WarmPoolRuntimePolicy

if TYPE_CHECKING:
    from shared.range_instantiation_policy import BackendAdmission

logger = logging.getLogger(__name__)

# The v1 warm target class the reconciler prepares for; the launch claim path must
# derive the same values for a claim to match (documented in _warm_pool_claim).
WARM_RANGE_SOURCE = RangeSource.MISSION_CONTROL
WARM_PURPOSE = InstantiationPurpose.LIVE_FIRE
_WARM_USER_EMAIL_DOMAIN = "warm-pool.invalid"
_WARM_EGRESS_MODE = "status-quo"


def _policy_fingerprint(policy: WarmPoolRuntimePolicy, bucket: WarmPoolBucketPolicy) -> str:
    """Return a stable fingerprint of the effective policy a generation is minted under."""
    return canonical_payload_digest(
        {
            "scale_down": policy.scale_down,
            "replacement": policy.replacement,
            "bucket": {
                "id": bucket.id,
                "backend": bucket.backend,
                "scenario": bucket.scenario,
                "capacity_partition": bucket.capacity_partition,
                "target": bucket.target,
                "minimum": bucket.minimum,
                "maximum": bucket.maximum,
                "idle_ttl_seconds": bucket.idle_ttl_seconds,
                "region": bucket.region or "",
                "access_mode": bucket.access_mode or "",
            },
        }
    )


def _bucket_compatibility_digest(bucket: WarmPoolBucketPolicy, *, package_digest: str, lock_digest: str) -> str:
    """Compute the compatibility digest a generation in this bucket must carry."""
    return compatibility_digest(
        CompatibilityKey(
            backend=bucket.backend,
            instantiation_purpose=WARM_PURPOSE.value,
            range_source=WARM_RANGE_SOURCE.value,
            workspace_isolation_class=ISOLATION_PERSONAL,
            egress_mode=_WARM_EGRESS_MODE,
            scenario=bucket.scenario,
            package_digest=package_digest,
            lock_digest=lock_digest,
        )
    )


def create_managed_warm_user() -> User:
    """Create an inactive, machine-marked system user that owns a warm generation.

    The ``@warm-pool.invalid`` email domain is the machine-checkable marker (mirrors
    the CTF spare managed-user pattern -- a shared low-level mechanism, not the CTF
    recovery policy). The user is inactive so it can never authenticate; it exists
    only to satisfy the ``(user_id, range_source)`` active-range uniqueness while the
    generation is system-owned, and is removed when the generation is claimed or
    retired.
    """
    token = secrets.token_hex(16)
    return User.objects.create_user(
        username=f"warm-{token}", email=f"{token}@{_WARM_USER_EMAIL_DOMAIN}", is_active=False
    )


def reconcile_warm_pool(*, now: datetime | None = None) -> dict[str, int]:
    """Run one warm-pool reconcile pass. Returns a bounded per-outcome summary."""
    moment = now or timezone.now()
    policy: WarmPoolRuntimePolicy = settings.WARM_POOL_POLICY
    summary = {"provisioned": 0, "retired": 0, "finalized": 0, "buckets": 0}
    if not policy.is_active():
        return summary
    from engine.services import retire_removed_bucket_generations

    for bucket in policy.buckets:
        summary["buckets"] += 1
        try:
            _reconcile_bucket(bucket, policy, moment, summary)
        except Exception:
            # A single bucket's failure must not stop the others; the next pass
            # retries. Bounded, sanitized log only.
            logger.exception("warm-pool reconcile failed for bucket=%s", bucket.id)
    # Retire generations whose bucket was removed/narrowed out of the effective
    # policy, so they stop being claimable rather than lingering globally.
    summary["retired"] += retire_removed_bucket_generations([b.id for b in policy.buckets])
    _emit_pool_gauges(policy)
    return summary


def _emit_pool_gauges(policy: WarmPoolRuntimePolicy) -> None:
    """Publish per-bucket pool-depth gauges to the WarmPool metrics namespace (#28)."""
    from engine.services import bucket_state_counts
    from shared.warm_pool.metrics import WarmPoolBucketSnapshot, emit_gauges

    snapshots = []
    for bucket in policy.buckets:
        counts = bucket_state_counts(bucket.id)
        snapshots.append(
            WarmPoolBucketSnapshot(
                bucket_id=bucket.id,
                backend=bucket.backend,
                region=bucket.region or "",
                ready=counts.get("ready", 0),
                provisioning=counts.get("provisioning", 0),
                unhealthy=counts.get("unhealthy", 0),
                claimed=counts.get("claimed", 0),
            )
        )
    emit_gauges(snapshots)


def _reconcile_bucket(
    bucket: WarmPoolBucketPolicy, policy: WarmPoolRuntimePolicy, moment: datetime, summary: dict[str, int]
) -> None:
    """Converge one bucket: finalize, recover stalled, retire stale/excess, replenish."""
    from engine.services import (
        active_generation_count,
        finalize_retiring_generations,
        recover_stalled_generations,
    )

    summary["finalized"] += finalize_retiring_generations(bucket.id)
    # Crash-safety: retire generations stuck non-terminal (a failed prepare/activate
    # or a dispatch that crashed before any result) so no strand keeps counting
    # toward the ceiling. Grace scales with the replenish cadence.
    stall_grace = max(600, policy.replenish_interval_seconds * 3)
    summary["retired"] += recover_stalled_generations(bucket.id, stall_grace_seconds=stall_grace, now=moment)

    identity = _resolve_bucket_identity(bucket)
    if identity is None:
        # The bucket's scenario no longer resolves to a registered source: retire
        # every unclaimed generation and provision nothing.
        summary["retired"] += _retire_all_ready(bucket)
        return
    package_digest, lock_digest = identity
    current_digest = _bucket_compatibility_digest(bucket, package_digest=package_digest, lock_digest=lock_digest)

    live_ready, retired = _retire_stale_ready(bucket, current_digest, moment)
    summary["retired"] += retired
    active = active_generation_count(bucket.id)
    active, retired = _scale_down_excess(bucket, policy, live_ready, active)
    summary["retired"] += retired
    summary["provisioned"] += _replenish_shortfall(bucket, policy, current_digest, active)


def _retire_all_ready(bucket: WarmPoolBucketPolicy) -> int:
    """Retire every unclaimed generation in a bucket (its scenario no longer resolves)."""
    from engine.services import ready_generations, retire_generation

    retired = 0
    for gen in ready_generations(bucket.id):
        if retire_generation(gen):
            retired += 1
    return retired


def _retire_stale_ready(bucket: WarmPoolBucketPolicy, current_digest: str, moment: datetime) -> tuple[list[Any], int]:
    """Retire ready generations past their idle deadline or carrying a stale digest.

    Returns ``(survivors, retired_count)`` -- the still-live ready generations plus
    how many were retired.
    """
    from engine.services import ready_generations, retire_generation

    live_ready: list[Any] = []
    retired = 0
    for gen in ready_generations(bucket.id):
        expired = gen.idle_deadline is not None and gen.idle_deadline <= moment
        incompatible = gen.compatibility_digest != current_digest
        if expired or incompatible:
            if retire_generation(gen):
                retired += 1
        else:
            live_ready.append(gen)
    return live_ready, retired


def _scale_down_excess(
    bucket: WarmPoolBucketPolicy, policy: WarmPoolRuntimePolicy, live_ready: list[Any], active: int
) -> tuple[int, int]:
    """Retire unclaimed generations above target per the scale-down order.

    Returns ``(active, retired_count)`` with ``active`` decremented for each retirement.
    """
    from engine.services import retire_generation

    retired = 0
    if active > bucket.target:
        excess = active - bucket.target
        victims = live_ready if policy.scale_down == "oldest-first" else list(reversed(live_ready))
        for gen in victims[:excess]:
            if retire_generation(gen):
                retired += 1
                active -= 1
    return active, retired


def _replenish_shortfall(
    bucket: WarmPoolBucketPolicy, policy: WarmPoolRuntimePolicy, current_digest: str, active: int
) -> int:
    """Warm-prepare up to the shortfall, bounded by maximum, ceiling, and concurrency.

    Returns the number of generations dispatched this pass.
    """
    from engine.services import total_active_generation_count

    ceiling = policy.max_total_ready or sum(b.maximum for b in policy.buckets)
    ceiling_headroom = max(0, ceiling - total_active_generation_count())
    budget = min(
        max(0, bucket.target - active),
        max(0, bucket.maximum - active),
        ceiling_headroom,
        policy.replenish_concurrency,
    )
    provisioned = 0
    for _ in range(budget):
        if _provision_warm_generation(bucket, policy, current_digest):
            provisioned += 1
    return provisioned


def _resolve_bucket_identity(bucket: WarmPoolBucketPolicy) -> tuple[str, str] | None:
    """Return the (package_digest, lock_digest) for the bucket's scenario, or None."""
    from cms.models import RaesPackageSource

    source = RaesPackageSource.objects.filter(scenario_id=bucket.scenario).order_by("-pk").first()
    if source is None or not source.package_digest or not source.lock_digest:
        logger.warning("warm-pool: bucket=%s scenario=%s has no registered source", bucket.id, bucket.scenario)
        return None
    return source.package_digest, source.lock_digest


def _provision_warm_generation(bucket: WarmPoolBucketPolicy, policy: WarmPoolRuntimePolicy, compatibility: str) -> bool:
    """Warm-prepare one system-owned, quarantined generation for a bucket.

    Returns True on a dispatched preparation. Failures are logged and swallowed so
    one bad preparation does not abort the pass; capacity drawn for a failed
    dispatch is released.
    """
    from cms.services._range_backend_admission import assert_backend_admitted

    # Admission FIRST, before allocating any managed user, so an unsupported or
    # mismatched bucket (explicitly-accepted configuration) does not leak an
    # inactive managed user every reconcile pass.
    backend_admission = assert_backend_admitted(WARM_PURPOSE, WARM_RANGE_SOURCE)
    if (
        backend_admission is None
        or backend_admission.backend != bucket.backend
        or not backend_supports_warm_activation(backend_admission.backend)
    ):
        logger.warning("warm-pool: bucket=%s backend not warm-capable; skipping", bucket.id)
        return False
    return _warm_prepare_dispatch(bucket, policy, compatibility, backend_admission)


def _warm_prepare_dispatch(
    bucket: WarmPoolBucketPolicy,
    policy: WarmPoolRuntimePolicy,
    compatibility: str,
    backend_admission: BackendAdmission,
) -> bool:
    """Reserve, draw capacity, and dispatch one warm-prepare (helper of ``_provision_warm_generation``).

    Returns True on a dispatched preparation, False on a capacity refusal or any
    failure. All allocated resources (managed user, capacity draw, reservation) are
    cleaned up on the non-dispatch paths.
    """
    from cms.models import RangeInstance, Request
    from cms.services._raes_range_create import (
        _audit_raes_range_provision,
        _dispatch_raes_package,
        _load_raes_source_or_raise,
    )
    from cms.services._range_launch_common import _reserve_active_range_slot
    from cms.services._range_workspace import admit_workspace_launch, resolve_launch_workspace
    from engine.services import (
        WarmGenerationDraft,
        admit_warm_generation_capacity,
        create_warm_generation,
        warm_capacity_scope_ref,
    )

    system_user = create_managed_warm_user()
    draw_key = uuid4()
    scope_ref = warm_capacity_scope_ref(settings.WARM_POOL_DEPLOYMENT_NAME, bucket.id)
    request_id: UUID | None = None
    try:
        source = _load_raes_source_or_raise(bucket.scenario)
        request_id = uuid4()
        workspace_id = resolve_launch_workspace(system_user, None)
        admit_workspace_launch(
            workspace_id=workspace_id,
            user=system_user,
            range_source=WARM_RANGE_SOURCE,
            instantiation_purpose=WARM_PURPOSE,
            correlation_key=request_id,
        )

        def _persist(cms_request: Request) -> RangeInstance:
            """Create the system-owned CMS RangeInstance row for the warm generation."""
            return RangeInstance.objects.create(
                request=cms_request,
                scenario_id=bucket.scenario,
                user_id=system_user.id,
                workspace_id=cms_request.workspace_id,
                range_source=WARM_RANGE_SOURCE.value,
                range_spec=None,
            )

        _rid, _req, _ri, egress_mode = _reserve_active_range_slot(
            system_user, WARM_RANGE_SOURCE, _persist, workspace_id, request_id
        )

        # Create the ledger row BEFORE dispatch so the provision suppresses
        # participant access (quarantine), and draw capacity before provider work.
        create_warm_generation(
            WarmGenerationDraft(
                bucket_id=bucket.id,
                compatibility_digest=compatibility,
                effective_policy_fingerprint=_policy_fingerprint(policy, bucket),
                backend=bucket.backend,
                range_source=WARM_RANGE_SOURCE.value,
                capacity_partition=bucket.capacity_partition,
                capacity_scope_ref=scope_ref,
                capacity_draw_key=draw_key,
                request_id=request_id,
                idle_deadline=timezone.now() + timedelta(seconds=bucket.idle_ttl_seconds),
            )
        )
        # Capacity admission is a real gate, not advisory: a refused (REJECTED)
        # capacity or cost assessment must stop the warm provision. Clean up the
        # reserved generation and skip rather than dispatching over the ceiling.
        admission = admit_warm_generation_capacity(scope_ref=scope_ref, draw_key=draw_key)
        if admission.blocking:
            logger.warning("warm-pool: capacity refused for bucket=%s; skipping preparation", bucket.id)
            _abandon_preparation(request_id, system_user, draw_key)
            return False

        _dispatch_raes_package(request_id, system_user, source, backend_admission, workspace_id, egress_mode)
        _audit_raes_range_provision(request_id, bucket.scenario, system_user, WARM_RANGE_SOURCE)
        return True
    except Exception:
        logger.exception("warm-pool: failed to prepare a generation for bucket=%s", bucket.id)
        _abandon_preparation(request_id, system_user, draw_key)
        return False


def _abandon_preparation(request_id: UUID | None, system_user: User | None, draw_key: UUID) -> None:
    """Clean up a warm preparation that was refused or failed before/at dispatch (#28).

    Releases the capacity draw, moves any created ledger row to a reconciler-owned
    retiring state and fails the CMS reservation so no stranded PROVISIONING row
    keeps counting toward the pool ceiling, and deletes the managed system user.
    Every step is best-effort and idempotent so cleanup never raises out of the pass.
    """
    from cms.models import RangeInstance
    from engine.services import release_warm_generation_capacity, retire_generations_for_request

    try:
        release_warm_generation_capacity(draw_key)
    except Exception:
        logger.exception("warm-pool cleanup: capacity release failed")
    if request_id is not None:
        try:
            retire_generations_for_request(request_id)
        except Exception:
            logger.exception("warm-pool cleanup: ledger retire failed")
        try:
            RangeInstance.objects.filter(request__request_id=request_id).update(status=ResourceStatus.FAILED.value)
        except Exception:
            logger.exception("warm-pool cleanup: range-instance fail-mark failed")
    _delete_managed_warm_user(system_user)


def _delete_managed_warm_user(system_user: User | None) -> None:
    """Delete the managed warm-pool system user, best-effort and marker-checked."""
    if system_user is None:
        return
    try:
        if str(getattr(system_user, "email", "")).endswith(f"@{_WARM_USER_EMAIL_DOMAIN}"):
            system_user.delete()
    except Exception:
        logger.exception("warm-pool cleanup: managed user delete failed")
