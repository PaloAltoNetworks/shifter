"""Write-once range-backend ownership binding helpers (#1666).

Shared by the cyberscript (:mod:`engine.services._range`) and ACES
(:mod:`engine.services._aces_range`) create services: map the trusted CMS
``BackendAdmission`` to the Range binding columns and enforce write-once
ownership on an idempotent create reuse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from shared.range_instantiation_policy import InstantiationPurpose, normalize_gcp_range_backend

from ._common import EngineError

if TYPE_CHECKING:
    from engine.models import Range
    from shared.range_instantiation_policy import BackendAdmission


def backend_binding_fields(backend_admission: BackendAdmission | None) -> dict[str, str]:
    """Map an admitted ``BackendAdmission`` to the write-once Range binding columns.

    Returns ``{}`` for a non-GCP launch (``backend_admission is None``) so the
    columns stay NULL. Backend and purpose are re-normalized through the single
    shared policy parser/enum so only closed policy values are ever persisted; the
    admission already holds normalized values, this is defense in depth.
    """
    if backend_admission is None:
        return {}
    return {
        "range_backend": normalize_gcp_range_backend(backend_admission.backend),
        "instantiation_purpose": InstantiationPurpose(backend_admission.purpose).value,
    }


def verify_existing_binding(
    existing_range: Range,
    request_id: UUID,
    backend_admission: BackendAdmission | None,
) -> None:
    """Enforce write-once binding on an idempotent create reuse.

    Idempotent create with the same request must carry the same binding; a
    *different* already-persisted binding is an ADR-039 ``conflict``, never a
    silent update. A NULL persisted binding (legacy row) is left untouched here --
    legacy repair is a destroy-time, ownership-evidence concern, not a create-time
    rewrite.
    """
    if backend_admission is None or not existing_range.range_backend:
        return
    expected = backend_binding_fields(backend_admission)
    if (
        existing_range.range_backend != expected["range_backend"]
        or existing_range.instantiation_purpose != expected["instantiation_purpose"]
    ):
        raise EngineError(
            f"Range backend binding conflict for request {request_id}: persisted "
            f"{existing_range.range_backend}/{existing_range.instantiation_purpose} differs from admitted "
            f"{expected['range_backend']}/{expected['instantiation_purpose']} (ADR-039 conflict; write-once)"
        )
