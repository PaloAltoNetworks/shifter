"""Compose the immutable operation-input projection (ADR-043).

Split out of ``launch_intents.py`` (Sonar S104), which grew past the file-size
budget when the RAES family was cut over in phase 5 (#1837). ``launch_intents``
owns *authorizing and minting* an operation generation; this module owns *what
that generation's immutable input contains*.

The projection is reference-only: it composes the existing persisted contracts
(the serialized RAES plan, ``DeliveryBinding``, the registry candidate shape,
the normalized backend vocabulary) rather than dumping ORM rows. Payload-owned
ownership, raw ``engine_instance.state``, and registry management metadata do
not cross the boundary.
"""

from __future__ import annotations

import json

from engine.models import Instance, Range, Request
from shared.raes.artifact_binding import ArtifactBinding
from shared.raes.content_delivery import DeliveryBinding
from shared.raes.operation_input import (
    RaesInputBindings,
    build_raes_operation_input,
    candidate_key,
    plan_image_lookup_keys,
)
from shared.raes.participant_access import ParticipantAccessBinding

__all__ = ["operation_input_payload"]


# Durable ownership discriminants persisted on ``engine_instance.state`` (#1666).
# Mirrors the resolution the provisioner used to perform itself; the Engine owns
# these rows, so it evaluates the evidence and ships only the normalized outcome.
_GDC_ASSET_TYPES = frozenset({"vm_runtime_vm", "scenario_pod"})
_GCE_ASSET_TYPE = "gce_vm"


def _resolve_backend_from_evidence(request: Request) -> str | None:
    """Resolve a legacy (NULL-binding) range's backend from ownership evidence.

    Returns the proven backend only when the evidence is unambiguous (exactly
    one backend across all request-owned instances); returns ``None`` for an
    empty, mixed, or unrecognized set so the consumer fails closed. Names,
    scenario shape, the current selector, and successful VM boot are not
    evidence -- after a ``gdc -> gce`` flip, guessing strands the range.
    """
    backends: set[str] = set()
    for state in Instance.objects.filter(request=request).values_list("state", flat=True):
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except (TypeError, ValueError):
                continue
        if not isinstance(state, dict):
            continue
        asset_type = str(state.get("asset_type", "")).strip()
        if asset_type == _GCE_ASSET_TYPE:
            backends.add("gce")
        elif asset_type in _GDC_ASSET_TYPES:
            backends.add("gdc")
    return next(iter(backends)) if len(backends) == 1 else None


def _resolved_range_backend(target: Range, request: Request) -> str | None:
    """Return the range's normalized backend binding, else the proven legacy one.

    ``request`` is the one already resolved by the caller, so the legacy
    evidence sweep is always scoped to a real request rather than re-deriving a
    nullable relation here.
    """
    if target.range_backend:
        return str(target.range_backend)
    return _resolve_backend_from_evidence(request)


def _raes_image_candidates(plan: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    """Project the enabled registry rows this plan can actually ask for.

    Scoped to the plan's own lookup keys (ADR-032-R2 authored source, else the
    node's OS family) so the tenant-wide registry never crosses the boundary
    wholesale. Disabled rows are excluded exactly as the direct
    ``WHERE enabled = TRUE`` read did, keeping a retired mapping fail-loud at
    realization.
    """
    from engine.models import RaesImageMapping

    keys = plan_image_lookup_keys(plan)
    if not keys:
        return {}
    projected: dict[str, list[dict[str, object]]] = {}
    rows = RaesImageMapping.objects.filter(source_name__in=list(keys), enabled=True).order_by(
        "provider", "source_name", "source_version"
    )
    for row in rows:
        projected.setdefault(candidate_key(str(row.provider), str(row.source_name)), []).append(
            {
                "source_version": row.source_version,
                "image_ref": row.image_ref,
                "machine_type": row.machine_type,
                "disk_size_gb": row.disk_size_gb,
                "disk_type": row.disk_type,
            }
        )
    return projected


def _raes_delivery_bindings(target: Range) -> list[DeliveryBinding]:
    """Rebuild this range's byte-free delivery bindings for transport."""
    from engine.models import RaesContentDeliveryBinding

    bindings = []
    for row in RaesContentDeliveryBinding.objects.filter(range=target).order_by("pk"):
        bindings.append(
            DeliveryBinding(
                content_address=row.content_address or None,
                sha256=row.sha256,
                storage_key=row.storage_key,
                byte_count=row.byte_count,
                binding_version=row.binding_version,
                resource_type=row.resource_type or None,
                resource_address=row.resource_address or None,
                payload_kind=row.payload_kind or None,
                install_policy=row.install_policy or None,
            )
        )
    return bindings


def _raes_access_bindings(target: Range) -> list[ParticipantAccessBinding]:
    """Rebuild this range's non-secret participant-access declarations (#1710)."""
    from engine.models import RaesParticipantAccessBinding

    return [
        ParticipantAccessBinding(
            target_address=row.target_address,
            channel=row.channel,
            account_address=row.account_address,
            binding_version=row.binding_version,
        )
        for row in RaesParticipantAccessBinding.objects.filter(range=target).order_by("pk")
    ]


def _raes_artifact_bindings(target: Range) -> list[ArtifactBinding]:
    """Rebuild this range's generation-fenced artifact-satisfaction bindings (#1580).

    The CMS launch resolved each authored artifact requirement to a concrete
    backend image and persisted it; the provisioner realizes exactly these,
    never re-resolving. Byte-free by construction -- no credential, URL, or
    payload is persisted or shipped.
    """
    from engine.models import RaesArtifactSatisfactionBinding

    return [
        ArtifactBinding(
            target=row.target_address,
            requirement_id=row.requirement_id,
            artifact_id=row.artifact_id,
            version=row.artifact_version,
            digest=row.digest,
            media_type=row.media_type,
            mechanism=row.mechanism,
            acquisition=row.acquisition,
            timing=row.timing,
            image_ref=row.image_ref,
            image_id=row.image_id,
            machine_type=row.machine_type,
            disk_size_gb=row.disk_size_gb,
            disk_type=row.disk_type,
        )
        for row in RaesArtifactSatisfactionBinding.objects.filter(range=target).order_by("pk")
    ]


def _raes_input_payload(target: Range, request: Request, *, suppress_access: bool = False) -> dict[str, object]:
    """Compose the RAES operation input (ADR-043 phase 5, #1837).

    Replaces direct provisioner reads with one immutable row: the serialized
    plan, the delivery bindings, the participant-access bindings, the fenced
    artifact bindings, the plan-scoped image candidates, and the normalized
    backend ownership.

    ``suppress_access`` (#28) drops the participant-access bindings so a warm-prepare
    provision realizes a system-owned, quarantined generation with no participant
    access; warm activation later carries the access bindings and realizes the
    claimant's fresh access.
    """
    plan = target.range_config or {}
    return build_raes_operation_input(
        plan=plan,
        bindings=RaesInputBindings(
            delivery=_raes_delivery_bindings(target),
            access=() if suppress_access else _raes_access_bindings(target),
            artifact=_raes_artifact_bindings(target),
        ),
        image_candidates=_raes_image_candidates(plan),
        range_backend=_resolved_range_backend(target, request),
        instantiation_purpose=target.instantiation_purpose or None,
        legacy_range_id=target.id,
        egress_mode=target.egress_mode,
    )


def _activation_input_payload(target: Range, request: Request) -> dict[str, object]:
    """Compose the warm-pool ``activate`` claimant projection (#28).

    Self-sufficient from the claimed warm-generation ledger row plus the Range,
    which has already been reassigned to the claimant at claim time. The claimant
    identity comes from this immutable projection, never from HTTP/env/argv
    (preflight #28 security gate 6).
    """
    from engine.models import WarmRangeGeneration
    from shared.warm_pool.activation_input import ActivationClaimant, ActivationGeneration, build_activation_input

    gen = (
        WarmRangeGeneration.objects.filter(request_id=request.request_id, state=WarmRangeGeneration.State.CLAIMED)
        .order_by("pk")
        .first()
    )
    if gen is None:
        raise ValueError("activation requires a claimed warm generation for the request")
    claimant = target.user
    purpose = target.instantiation_purpose or "live_fire"
    return build_activation_input(
        claimant=ActivationClaimant(
            user_id=int(target.cms_user_id or claimant.id),
            username=str(claimant.username),
            workspace_id=int(target.workspace_id),
        ),
        generation=ActivationGeneration(
            range_source=gen.range_source,
            instantiation_purpose=str(purpose),
            range_backend=str(target.range_backend or gen.backend),
            legacy_range_id=int(target.id),
            compatibility_digest=gen.compatibility_digest,
            prepared_generation_fence=str(gen.operation_id or ""),
        ),
        # The full realization projection (plan + the now-unsuppressed participant
        # access bindings) so the provisioner can locate the realized hosts and
        # realize the claimant's fresh access.
        raes_input=_raes_input_payload(target, request),
    )


def _request_has_pending_warm_generation(request: Request) -> bool:
    """Return True when a warm generation is provisioning against this request (#28).

    The signal that a ``raes-range provision`` is a *warm-prepare*: its participant
    access is suppressed so the realized generation is quarantined until activation.
    """
    from engine.models import WarmRangeGeneration

    return WarmRangeGeneration.objects.filter(
        request_id=request.request_id, state=WarmRangeGeneration.State.PROVISIONING
    ).exists()


def _range_operation_payload(target: Range, resource: str, request: Request, operation: str) -> dict[str, object]:
    """Compose the operation-input projection for a :class:`Range` target."""
    if resource == "raes-range" and operation == "activate":
        return _activation_input_payload(target, request)
    if resource == "raes-range":
        # A warm-prepare provision suppresses participant access so the realized
        # generation is system-owned and quarantined until it is claimed and
        # activated (#28).
        return _raes_input_payload(target, request, suppress_access=_request_has_pending_warm_generation(request))
    return {
        "range_spec": target.range_config or {},
        "legacy_range_backend": _resolved_range_backend(target, request),
        # Effective egress posture pinned at create (PLAT-238, ADR-017-R5).
        # Delivered per-range so the provisioner realizes it from the operation
        # input, never from the deployment-owned RANGE_EGRESS_MODE env once a
        # decision is pinned. Always present on a new generation; the provisioner
        # parser fails closed on absence rather than defaulting (ADR-043 window).
        "egress_mode": target.egress_mode,
    }


def operation_input_payload(
    target: Range | Instance, resource: str, request: Request, *, operation: str = "provision"
) -> dict[str, object]:
    """Compose the immutable operation-input projection from engine-owned models.

    A reference-only projection of the existing persisted contracts, not an ORM
    dump. The RAES family consumes the full projection (#1837); the cyberscript
    range family still reads most of its inputs directly, and takes only the
    normalized legacy backend it can no longer resolve for itself. The warm-pool
    ``activate`` operation (#28) carries the claimant projection instead.
    """
    if isinstance(target, Range):
        return _range_operation_payload(target, resource, request, operation)
    return {"role": str(target.role), "os_type": str(target.os_type)}
