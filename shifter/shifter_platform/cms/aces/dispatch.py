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
from typing import Any

from engine.services import create_aces_range
from shared.aces.dispatch_port import ShifterDispatchResult

__all__ = ["CmsAcesDispatchPort"]


@dataclass(frozen=True)
class CmsAcesDispatchPort:
    """Realize a serialized ACES plan through the engine ACES range service.

    Constructed per launch with the CMS launch context (the owning user id and
    the Shifter ``request_id`` the operation is keyed by). The RuntimeTarget
    backend validates + serializes the plan and calls :meth:`realize`.
    """

    user_id: int
    request_id: str

    def realize(self, compiled_plan: dict[str, Any]) -> ShifterDispatchResult:
        ref = create_aces_range(
            request_id=self.request_id,
            user_id=self.user_id,
            compiled_plan=compiled_plan,
        )
        return ShifterDispatchResult(
            request_id=ref.request_id, accepted=ref.accepted, status=ref.status, range_id=ref.range_id
        )
