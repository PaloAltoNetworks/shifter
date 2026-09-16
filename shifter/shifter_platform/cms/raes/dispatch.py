"""CMS-side concrete RAES provisioning dispatch port (ADR-031, ADR-032, ADR-024).

Concrete implementation of
:class:`shared.raes.dispatch_port.ShifterProvisioningDispatchPort`. It hands the
serialized RAES ``ProvisioningPlan`` to the engine service seam
(:func:`engine.services.create_raes_range`), which persists it keyed by
``request_id``, writes the operation-receipt sidecar, and dispatches the
provisioner ``raes-range`` task.

Conformance boundary (ADR-031-R1, ADR-032): the RAES code path imports **no**
cyberscript module and carries **no** cyberscript semantics. The persisted
artifact is the serialized RAES plan itself (a plain dict, self-describing via
its ``kind``/``raes_version``) -- not a cyberscript envelope and not a
Shifter-owned spec. This module imports only ``shared.raes`` and the public
``engine.services`` facade.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings
from installation.range_egress import RangeEgressMode

from engine.services import RangeBindings, create_raes_range
from shared.raes.dispatch_port import ShifterDispatchResult

if TYPE_CHECKING:
    from pathlib import Path

    from shared.raes.artifact_binding import ArtifactBinding
    from shared.raes.artifact_inventory import ArtifactRequirements, ArtifactSupply, BackendArtifact
    from shared.raes.content_delivery import DeliveryBinding
    from shared.raes.participant_access import ParticipantAccessBinding
    from shared.range_instantiation_policy import BackendAdmission

__all__ = ["CmsRaesDispatchPort"]

# Realization backends whose tenant image registry can own portable artifacts
# (the RAES-native GCE adapter). A backend outside this set has no artifact
# inventory, so resolution is skipped rather than querying an unknown provider.
_ARTIFACT_REGISTRY_PROVIDERS = frozenset({"gce"})


@dataclass(frozen=True)
class CmsRaesDispatchPort:
    """Realize a serialized RAES plan through the engine RAES range service.

    Constructed per launch with the CMS launch context (the owning user id and
    the Shifter ``request_id`` the operation is keyed by). The RuntimeTarget
    backend validates + serializes the plan and calls :meth:`realize`.

    ``backend_admission`` is the trusted #1348 admission result captured at the
    CMS live-fire gate and carried beside the RAES plan (never inside it, per
    ADR-031-R1/R2). The engine binds the immutable #1666 (backend, purpose)
    ownership fields from it at create; ``None`` on non-GCP providers.

    ``pack_root`` is the live, digest-verified pack directory for this launch. It
    is the one point where the pack bytes and the compiled plan coexist (#1564),
    so :meth:`realize` prepares source-backed content delivery here: it
    materializes each source-backed content item, promotes it content-addressed to
    object storage, and hands the engine the byte-free delivery bindings to persist
    beside the plan (ADR-032-R3). ``None`` only in tests / plans that carry no
    source-backed content.

    ``workspace_id`` is the trusted #1325 tenancy scope resolved and authorized by
    the CMS launch facade. It rides beside the plan for the same reason
    ``backend_admission`` does: Engine persists it, and never resolves or
    authorizes a workspace itself (ADR-046-R1/R3).
    """

    user_id: int
    request_id: str
    # Required: the port cannot realize a range without a tenancy scope, and a
    # nullable field here would just push the failure into the Engine boundary.
    workspace_id: int
    backend_admission: BackendAdmission | None = None
    pack_root: Path | None = None
    # Effective range egress posture resolved under the workspace mutex by the CMS
    # launch-admission seam (PLAT-238, ADR-017-R5). Rides beside the plan like
    # ``workspace_id``; the Engine pins it on the range at create. Defaults to the
    # compatibility ``status-quo`` for constructors that predate the field.
    egress_mode: str = RangeEgressMode.STATUS_QUO.value

    def realize(
        self,
        compiled_plan: dict[str, Any],
        participant_access: Sequence[ParticipantAccessBinding] = (),
    ) -> ShifterDispatchResult:
        delivery_bindings = self._prepare_delivery(compiled_plan)
        artifact_bindings = self._resolve_artifact_bindings(compiled_plan)
        ref = create_raes_range(
            request_id=self.request_id,
            user_id=self.user_id,
            compiled_plan=compiled_plan,
            backend_admission=self.backend_admission,
            bindings=RangeBindings(
                delivery=delivery_bindings,
                participant_access=tuple(participant_access),
                artifact=artifact_bindings,
            ),
            workspace_id=self.workspace_id,
            egress_mode=self.egress_mode,
        )
        return ShifterDispatchResult(
            request_id=ref.request_id, accepted=ref.accepted, status=ref.status, range_id=ref.range_id
        )

    def _resolve_artifact_bindings(self, compiled_plan: dict[str, Any]) -> tuple[ArtifactBinding, ...]:
        """Resolve authored artifact requirements to fenced bindings at launch (#1580).

        ALWAYS runs the resolver over the plan's authored requirements -- it never
        short-circuits on the backend before inspecting requirements. A plan with no
        artifact requirement resolves to no bindings; a plan carrying a requirement
        the selected backend cannot satisfy (including a backend with no artifact
        registry, whose inventory is empty) fails closed: ``resolve_plan_artifact_bindings``
        raises, the dispatch is not accepted, and the range reservation is marked
        FAILED rather than a missing binding letting the provisioner fall through to
        legacy resolution. An exact requirement is never substituted (ADR-034-R8;
        codex #1580 review).
        """
        from shared.raes.artifact_inventory import resolve_plan_artifact_bindings
        from shared.raes.manifest import shifter_artifact_mechanism_capabilities, shifter_backend_apparatus

        return resolve_plan_artifact_bindings(
            compiled_plan,
            inventory=self._backend_inventory(),
            capabilities=shifter_artifact_mechanism_capabilities(),
            backend=shifter_backend_apparatus(),
        )

    def artifact_supply(self, requirements: ArtifactRequirements) -> ArtifactSupply:
        """Give planning the same admitted backend inventory used to fence dispatch."""
        from shared.raes.artifact_inventory import build_artifact_supply

        return build_artifact_supply(requirements, self._backend_inventory())

    def _backend_inventory(self) -> tuple[BackendArtifact, ...]:
        """Return the selected backend's owned artifact inventory, or empty when it has none.

        A backend outside the artifact-registry set (or an absent admission) owns no
        portable artifacts, so its inventory is empty and any authored requirement
        resolves unsatisfiable -- the resolver then fails the launch closed rather
        than skipping resolution.
        """
        provider = self.backend_admission.backend if self.backend_admission is not None else None
        if provider not in _ARTIFACT_REGISTRY_PROVIDERS:
            return ()
        from engine.services import list_backend_artifacts

        return tuple(list_backend_artifacts(provider=provider))

    def _prepare_delivery(self, compiled_plan: dict[str, Any]) -> tuple[DeliveryBinding, ...]:
        """Materialize + promote source-backed content, returning byte-free bindings.

        Returns an empty tuple for the common case of a plan with no source-backed
        content (``prepare_content_delivery`` short-circuits before touching the
        pack or object storage). Any preparation failure raises
        ``ContentDeliveryError``, which the RuntimeTarget apply boundary turns into
        a non-accepted dispatch so the range reservation is marked FAILED.
        """
        from shared.raes.content_delivery_prep import (
            DeliveryTarget,
            has_source_backed_content,
            prepare_content_delivery,
        )

        # Cheap precheck: skip object-storage / pack resolution entirely for the
        # common plan with no source-backed content.
        if not has_source_backed_content(compiled_plan):
            return ()

        from shared.cloud import get_object_storage

        target = DeliveryTarget(
            storage=get_object_storage(),
            bucket=settings.STORAGE_BUCKET_NAME,
            prefix=settings.RAES_CONTENT_DELIVERY_PREFIX,
            max_payload_bytes=settings.RAES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES,
        )
        return prepare_content_delivery(pack_root=self.pack_root, serialized_plan=compiled_plan, target=target)
