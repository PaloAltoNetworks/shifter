"""Engine-side creation and dispatch for the canonical RAES path (ADR-031).

The persisted truth is the serialized RAES ``ProvisioningPlan`` stored in
``mission_control_range.range_config`` and realized by the provisioner's
``raes-range`` command. This module is reached through the RAES dispatch port
(``cms.raes.dispatch``) and is the only range-creation authority.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from installation.range_egress import RangeEgressMode

from engine.ecs import start_raes_range_provisioning
from shared.enums import RequestType
from shared.raes.artifact_binding import ArtifactBinding
from shared.raes.content_delivery import DeliveryBinding
from shared.raes.participant_access import ParticipantAccessBinding
from shared.remote_access import build_openvpn_capability, raes_member_target_ref

from ._common import _persist_task_arn
from ._range_backend_binding import (
    assert_backend_supports_egress,
    backend_binding_fields,
    egress_binding_fields,
    require_workspace_binding,
    verify_existing_binding,
    verify_existing_egress_binding,
    verify_existing_workspace_binding,
)
from ._range_placement import select_placement_zone
from ._runtime_plugin_bindings import (
    persist_runtime_plugin_pin,
    resolve_runtime_plugin_pin,
    retained_runtime_plugin_pin,
)

if TYPE_CHECKING:
    from engine.models import Range
    from shared.range_instantiation_policy import BackendAdmission
    from shared.runtime_plugin_binding import RuntimePluginScope

__all__ = [
    "RaesRangeRef",
    "RangeBindings",
    "create_raes_range",
    "dispatch_created_raes_range",
    "grant_raes_remote_access",
    "mint_remote_access_capability",
]


@dataclass(frozen=True)
class RaesRangeRef:
    """IDs/status returned to the dispatch port after an RAES range is accepted."""

    request_id: str
    range_id: str
    status: str
    accepted: bool


@dataclass(frozen=True)
class RangeBindings:
    """The byte-free sidecar bindings persisted beside a Range, in one argument.

    Groups the three binding collections ``create_raes_range`` persists in the
    same transaction as the Range -- content delivery (#1564, ``delivery``),
    participant access (#1710, ``participant_access``), and generation-fenced
    artifacts (#1580, ``artifact``) -- so the create seam takes one cohesive
    argument. All three default empty; the common create passes none.
    """

    delivery: tuple[DeliveryBinding, ...] = ()
    participant_access: tuple[ParticipantAccessBinding, ...] = ()
    artifact: tuple[ArtifactBinding, ...] = ()
    runtime_plugin_scope: RuntimePluginScope | None = None
    # CMS may finish downward authorization after Range creation signals, then
    # dispatch in the same enclosing transaction. No worker sees a partial launch.
    defer_dispatch: bool = False
    # The CMS-admitted OpenVPN credential deadline (the lease ceiling), or None
    # when the launch requests no VPN (ADR-039-R10, #2030). Engine mints the
    # capability against the persisted participant access and reserves a slot.
    openvpn_deadline: datetime | None = None


def create_raes_range(
    *,
    request_id: str | UUID,
    user_id: int,
    compiled_plan: dict[str, Any],
    workspace_id: int,
    egress_mode: str = RangeEgressMode.STATUS_QUO.value,
    backend_admission: BackendAdmission | None = None,
    bindings: RangeBindings | None = None,
) -> RaesRangeRef:
    """Create + dispatch an RAES-native range from a serialized RAES plan.

    Persists an ``engine.models.Request`` and ``engine.models.Range`` (with
    ``range_config`` = the serialized RAES ProvisioningPlan, a plain dict that is
    self-describing via its ``kind``/``raes_version`` -- no cyberscript
    envelope and no Shifter-owned spec, ADR-031-R1 / ADR-032) keyed by
    ``request_id``, writes an ``operation_receipt`` sidecar, and dispatches the
    provisioner ``raes-range provision`` task. Idempotent on ``request_id``. On a
    dispatch failure the range is marked FAILED and the error re-raised, so a
    dispatch failure is never silent (mirrors ``create_range``).

    ``backend_admission`` is the trusted #1348 admission result carried beside the
    RAES plan (never inside it, ADR-031-R1/R2). The normalized (backend, purpose)
    is persisted as the write-once #1666 ownership binding in the same transaction
    as the Range, before dispatch; ``None`` on non-GCP providers.

    ``workspace_id`` is the trusted #1325 tenancy scope resolved and authorized by
    the CMS launch facade and carried the same way. It is **required** and
    persisted in the same transaction, so a range is never visible -- briefly or
    durably -- without its scope (ADR-046-R3).

    ``bindings`` groups the byte-free sidecar identities that ride beside the plan
    (see :class:`RangeBindings`); each collection is persisted in the same
    transaction as the Range. On the idempotent existing-range reuse path bindings
    are not re-created -- the first create already persisted them.

    ``bindings.delivery`` are the #1564 ``DeliveryBinding`` identities, each
    persisted as one ``engine.models.RaesContentDeliveryBinding`` row.

    ``bindings.participant_access`` are the #1710 non-secret
    ``ParticipantAccessBinding`` declarations, persisted as
    ``engine.models.RaesParticipantAccessBinding`` rows (ADR-032-R10). Because they
    are the immutable declaration the realized access is later compared against, an
    idempotent replay of the same ``request_id`` carrying *different* access intent
    is rejected rather than silently reusing the first declaration.

    ``bindings.artifact`` are the #1580 generation-fenced ``ArtifactBinding``
    decisions -- each authored artifact requirement the CMS launch resolved to a
    concrete backend image -- persisted as ``engine.models.RaesArtifactSatisfactionBinding``
    rows (ADR-034-R8). The provisioner realizes exactly these and never
    re-resolves; on the idempotent reuse path they are not re-created.
    """
    bindings = bindings or RangeBindings()
    # Imported lazily so importing the ``engine`` app does not define models
    # before the app registry is ready.
    from engine.models import Range, Request

    require_workspace_binding(workspace_id)
    request_uuid = request_id if isinstance(request_id, UUID) else UUID(str(request_id))

    existing = Range.objects.filter(request__request_id=request_uuid).first()
    if existing is not None:
        verify_existing_binding(existing, request_uuid, backend_admission)
        verify_existing_workspace_binding(existing, request_uuid, workspace_id)
        verify_existing_egress_binding(existing, request_uuid, egress_mode)
        _verify_existing_participant_access(existing, bindings.participant_access)
        _verify_existing_plugin_scope(existing, bindings.runtime_plugin_scope)
        _verify_existing_remote_access(existing, bindings.openvpn_deadline)
        return RaesRangeRef(
            request_id=str(request_uuid), range_id=str(existing.uuid), status=existing.status, accepted=True
        )

    binding_fields = backend_binding_fields(backend_admission)
    egress_fields = egress_binding_fields(egress_mode)
    assert_backend_supports_egress(binding_fields.get("range_backend"), egress_fields["egress_mode"])
    capability = mint_remote_access_capability(
        bindings.participant_access,
        bindings.openvpn_deadline,
        str(binding_fields.get("range_backend") or ""),
    )
    user_model = get_user_model()
    with transaction.atomic():
        scope = bindings.runtime_plugin_scope
        pin = (
            resolve_runtime_plugin_pin(scope, compiled_plan, backend=str(binding_fields.get("range_backend") or ""))
            if scope
            else None
        )
        user = user_model.objects.get(id=user_id)
        request = Request.objects.create(request_id=request_uuid, request_type=RequestType.RANGE.value, user=user)
        subnet_index = Range.allocate_subnet_index()
        # #2029 realized multi-region placement: pick the zone from the
        # RANGE_NETWORK_ZONES pool in the same transaction as the slot (empty keeps
        # single-zone). The provisioner reads it back and never recomputes.
        placement_zone = select_placement_zone(subnet_index - 1)
        range_obj = Range.objects.create(
            uuid=uuid4(),
            user=user,
            request=request,
            cms_user_id=user_id,
            status=Range.Status.PROVISIONING,
            subnet_index=subnet_index,
            placement_zone=placement_zone,
            resource_generation=uuid4() if binding_fields.get("range_backend") == "ec2" else None,
            range_config=compiled_plan,
            workspace_id=workspace_id,
            remote_access_capability=capability,
            **binding_fields,
            **egress_fields,
        )
        _persist_range_bindings(range_obj, bindings)
        persist_runtime_plugin_pin(range_obj, pin)
        _write_operation_receipt(request_uuid, range_id=str(range_obj.uuid))

    if bindings.defer_dispatch:
        return RaesRangeRef(str(request_uuid), str(range_obj.uuid), range_obj.status, True)
    return dispatch_created_raes_range(request_uuid)


def mint_remote_access_capability(
    participant_access: Sequence[ParticipantAccessBinding],
    deadline: datetime | None,
    range_backend: str,
) -> dict[str, object] | None:
    """Mint OpenVPN authority for the sole participant-access target, when requested.

    ``deadline`` is the CMS-admitted credential deadline (the lease ceiling,
    ADR-039-R10). A scenario that does not declare exactly one participant-access
    target launches without VPN. The GCE range-cell backend is the only RAES
    adapter that realizes the gateway (EC2 is #2443), so a requested deadline on
    any other backend fails closed before the Range or its pool slot exists.
    """
    if deadline is None:
        return None
    if range_backend != "gce":
        raise ValueError("OpenVPN access is not realized by the selected range backend")
    targets = {binding.target_address for binding in participant_access}
    if len(targets) != 1:
        return None
    return build_openvpn_capability(raes_member_target_ref(next(iter(targets))), deadline)


def _verify_existing_remote_access(existing: Range, deadline: datetime | None) -> None:
    """Reject an idempotent replay that requests different OpenVPN authority."""
    from engine.models import RaesParticipantAccessBinding

    access = [
        ParticipantAccessBinding(row.target_address, row.channel, row.account_address)
        for row in RaesParticipantAccessBinding.objects.filter(range=existing)
    ]
    expected = mint_remote_access_capability(access, deadline, str(existing.range_backend or ""))
    if existing.remote_access_capability != expected:
        raise ValueError("RAES range replay requests different OpenVPN authority than the persisted capability")


def grant_raes_remote_access(request_id: UUID, deadline: datetime | None) -> bool:
    """Mint the claimant's OpenVPN authority on a just-claimed warm generation (#28, #2030).

    Runs inside the CMS claim transaction after the ownership rehome, so the
    activation input composed afterwards carries the capability and the profile
    is minted for the claimant. A warm generation is prepared without VPN, so a
    persisted capability or binding here is a contract violation. Returns whether
    a capability was granted.
    """
    from engine.models import RaesParticipantAccessBinding, Range

    if deadline is None:
        return False
    range_obj = Range.objects.get(request__request_id=request_id)
    if range_obj.remote_access_capability is not None or range_obj.vpn_access_binding is not None:
        raise ValueError("A warm generation must not hold OpenVPN authority before its claim")
    access = [
        ParticipantAccessBinding(row.target_address, row.channel, row.account_address)
        for row in RaesParticipantAccessBinding.objects.filter(range=range_obj)
    ]
    capability = mint_remote_access_capability(access, deadline, str(range_obj.range_backend or ""))
    if capability is None:
        return False
    with transaction.atomic():
        updated = Range.objects.filter(pk=range_obj.pk, remote_access_capability__isnull=True).update(
            remote_access_capability=capability,
            updated_at=timezone.now(),
        )
    if updated != 1:
        raise ValueError("A warm generation's OpenVPN authority changed during its claim")
    return True


def _verify_existing_plugin_scope(existing: Range, scope: RuntimePluginScope | None) -> None:
    """Reject replay that changes the administrator-selected tenant or pack revision."""
    pin = retained_runtime_plugin_pin(existing)
    if pin is not None and (
        scope is None
        or pin.organization_uuid != scope.organization_uuid
        or pin.pack_digest != scope.pack_digest
        or pin.pack_id != scope.pack_id
    ):
        raise ValueError("Range replay cannot change its runtime plugin pack identity")


def dispatch_created_raes_range(request_uuid: UUID) -> RaesRangeRef:
    """Dispatch an already persisted range through the incumbent launch outbox."""
    from engine.models import Range

    range_obj = Range.objects.get(request__request_id=request_uuid)
    try:
        task_ref = start_raes_range_provisioning(request_uuid)
    except Exception:
        range_obj.status = Range.Status.FAILED
        range_obj.error_message = "Provisioning dispatch failed"
        range_obj.save(update_fields=["status", "error_message", "updated_at"])
        from ._receipt import revoke_receipt_verifier

        revoke_receipt_verifier(request_uuid)
        raise
    if task_ref:
        _persist_task_arn(range_obj, "provision", task_ref)

    return RaesRangeRef(
        request_id=str(request_uuid), range_id=str(range_obj.uuid), status=range_obj.status, accepted=True
    )


def _persist_range_bindings(range_obj: Range, bindings: RangeBindings) -> None:
    """Persist every byte-free RAES sidecar binding in the range transaction."""
    from engine.models import (
        RaesArtifactSatisfactionBinding,
        RaesContentDeliveryBinding,
        RaesParticipantAccessBinding,
    )

    RaesContentDeliveryBinding.objects.bulk_create(
        RaesContentDeliveryBinding(
            range=range_obj,
            content_address=binding.content_address or "",
            resource_type=binding.resource_type or "",
            resource_address=binding.resource_address or "",
            payload_kind=binding.payload_kind or "",
            install_policy=binding.install_policy or "",
            sha256=binding.sha256,
            storage_key=binding.storage_key,
            byte_count=binding.byte_count,
            binding_version=binding.binding_version,
        )
        for binding in bindings.delivery
    )
    RaesParticipantAccessBinding.objects.bulk_create(
        RaesParticipantAccessBinding(
            range=range_obj,
            target_address=binding.target_address,
            channel=binding.channel,
            account_address=binding.account_address,
            binding_version=binding.binding_version,
        )
        for binding in bindings.participant_access
    )
    RaesArtifactSatisfactionBinding.objects.bulk_create(
        RaesArtifactSatisfactionBinding(
            range=range_obj,
            target_address=binding.target,
            requirement_id=binding.requirement_id,
            artifact_id=binding.artifact_id,
            artifact_version=binding.version,
            digest=binding.digest,
            media_type=binding.media_type,
            mechanism=binding.mechanism,
            acquisition=binding.acquisition,
            timing=binding.timing,
            image_ref=binding.image_ref,
            image_id=binding.image_id,
            machine_type=binding.machine_type,
            disk_size_gb=binding.disk_size_gb,
            disk_type=binding.disk_type,
            management_ssh_port=binding.management_ssh_port,
            management_ssh_username=binding.management_ssh_username,
            binding_version=1,
        )
        for binding in bindings.artifact
    )


def _verify_existing_participant_access(
    existing: Range,
    participant_access: tuple[ParticipantAccessBinding, ...],
) -> None:
    """Reject an idempotent replay that carries different access intent (#1710).

    The persisted rows are the immutable declaration the realized access binding
    is later compared against. Silently reusing the first declaration for a
    replay that now declares different access would let a second launch of the
    same ``request_id`` realize access the caller did not ask for, so a mismatch
    fails closed instead.
    """
    from engine.models import RaesParticipantAccessBinding

    persisted = {
        (row.target_address, row.channel, row.account_address)
        for row in RaesParticipantAccessBinding.objects.filter(range=existing)
    }
    requested = {(binding.target_address, binding.channel, binding.account_address) for binding in participant_access}
    if persisted != requested:
        raise ValueError("RAES range replay carries different participant access intent than the persisted binding")


def _write_operation_receipt(request_id: UUID, *, range_id: str) -> None:
    """Write the idempotent operation_receipt sidecar for an accepted provision."""
    # Lazy import: shared.raes.operations pulls shared.models, which must not load
    # during app population (mirrors _raes_status.py).
    from shared.raes.operations import persist_operation_receipt_record

    operation_id = str(request_id)
    persist_operation_receipt_record(
        request_id=request_id,
        operation_id=operation_id,
        source_timestamp=timezone.now(),
        payload={"operation_id": operation_id, "accepted": True, "status": "accepted"},
        range_id=range_id,
    )
