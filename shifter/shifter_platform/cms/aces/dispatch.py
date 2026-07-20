"""CMS-side concrete ACES provisioning dispatch port (ADR-031, ADR-032, ADR-024).

Concrete implementation of
:class:`shared.aces.dispatch_port.ShifterProvisioningDispatchPort`. It hands the
serialized ACES ``ProvisioningPlan`` to the engine service seam
(:func:`engine.services.create_aces_range`), which persists it keyed by
``request_id``, writes the operation-receipt sidecar, and dispatches the
provisioner ``aces-range`` task.

Conformance boundary (ADR-031-R1, ADR-032): the ACES code path imports **no**
cyberscript module and carries **no** cyberscript semantics. The persisted
artifact is the serialized ACES plan itself (a plain dict, self-describing via
its ``kind``/``aces_sdl_version``) -- not a cyberscript envelope and not a
Shifter-owned spec. This module imports only ``shared.aces`` and the public
``engine.services`` facade.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.conf import settings

from engine.services import create_aces_range
from shared.aces.dispatch_port import ShifterDispatchResult

if TYPE_CHECKING:
    from pathlib import Path

    from shared.aces.content_delivery import DeliveryBinding
    from shared.range_instantiation_policy import BackendAdmission

__all__ = ["CmsAcesDispatchPort"]


@dataclass(frozen=True)
class CmsAcesDispatchPort:
    """Realize a serialized ACES plan through the engine ACES range service.

    Constructed per launch with the CMS launch context (the owning user id and
    the Shifter ``request_id`` the operation is keyed by). The RuntimeTarget
    backend validates + serializes the plan and calls :meth:`realize`.

    ``backend_admission`` is the trusted #1348 admission result captured at the
    CMS live-fire gate and carried beside the ACES plan (never inside it, per
    ADR-031-R1/R2). The engine binds the immutable #1666 (backend, purpose)
    ownership fields from it at create; ``None`` on non-GCP providers.

    ``pack_root`` is the live, digest-verified pack directory for this launch. It
    is the one point where the pack bytes and the compiled plan coexist (#1564),
    so :meth:`realize` prepares source-backed content delivery here: it
    materializes each source-backed content item, promotes it content-addressed to
    object storage, and hands the engine the byte-free delivery bindings to persist
    beside the plan (ADR-032-R3). ``None`` only in tests / plans that carry no
    source-backed content.
    """

    user_id: int
    request_id: str
    backend_admission: BackendAdmission | None = None
    pack_root: Path | None = None

    def realize(self, compiled_plan: dict[str, Any]) -> ShifterDispatchResult:
        delivery_bindings = self._prepare_delivery(compiled_plan)
        ref = create_aces_range(
            request_id=self.request_id,
            user_id=self.user_id,
            compiled_plan=compiled_plan,
            backend_admission=self.backend_admission,
            delivery_bindings=delivery_bindings,
        )
        return ShifterDispatchResult(
            request_id=ref.request_id, accepted=ref.accepted, status=ref.status, range_id=ref.range_id
        )

    def _prepare_delivery(self, compiled_plan: dict[str, Any]) -> tuple[DeliveryBinding, ...]:
        """Materialize + promote source-backed content, returning byte-free bindings.

        Returns an empty tuple for the common case of a plan with no source-backed
        content (``prepare_content_delivery`` short-circuits before touching the
        pack or object storage). Any preparation failure raises
        ``ContentDeliveryError``, which the RuntimeTarget apply boundary turns into
        a non-accepted dispatch so the range reservation is marked FAILED.
        """
        from shared.aces.content_delivery_prep import (
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
            prefix=settings.ACES_CONTENT_DELIVERY_PREFIX,
            max_payload_bytes=settings.ACES_CONTENT_DELIVERY_MAX_PAYLOAD_BYTES,
        )
        return prepare_content_delivery(pack_root=self.pack_root, serialized_plan=compiled_plan, target=target)
