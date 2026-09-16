"""Write-once range-backend ownership binding helpers (#1666).

Shared by the cyberscript (:mod:`engine.services._range`) and RAES
(:mod:`engine.services._raes_range`) create services: map the trusted CMS
``BackendAdmission`` to the Range binding columns and enforce write-once
ownership on an idempotent create reuse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from installation.range_egress import RangeEgressMode

from shared.range_instantiation_policy import (
    InstantiationPurpose,
    evaluate_gcp_backend_admission,
    normalize_gcp_range_backend,
)

from ._common import EngineError

if TYPE_CHECKING:
    from engine.models import Range
    from shared.range_instantiation_policy import BackendAdmission


def require_workspace_binding(workspace_id: int | None) -> None:
    """Refuse to create a range with no tenancy scope (#1325, ADR-046-R3).

    The binding is supplied by the trusted CMS launch facade, like
    ``BackendAdmission`` above. Accepting ``None`` here would let a new or
    refactored caller persist an unscoped range indistinguishable from a legacy
    pre-#1325 row -- the ambiguity the non-null scope columns and this guard
    exist to remove.
    """
    if workspace_id is None:
        raise EngineError("A range cannot be created without a workspace binding")


def backend_binding_fields(backend_admission: BackendAdmission | None) -> dict[str, str]:
    """Map an admitted ``BackendAdmission`` to the write-once Range binding columns.

    Returns ``{}`` for a non-GCP launch (``backend_admission is None``) so the
    columns stay NULL.

    ``BackendAdmission`` is a plain constructible dataclass, so ``admitted=True``
    from an arbitrary in-process caller is not by itself authority (#1354). The
    pair is re-evaluated here against the closed default-deny policy -- without
    rereading the environment selector -- so a fabricated, denied, or malformed
    pair can never be persisted as ownership. This is the Engine-side half of the
    admission the CMS service boundary already performed.
    """
    if backend_admission is None:
        return {}
    try:
        backend = normalize_gcp_range_backend(backend_admission.backend)
        purpose = InstantiationPurpose(backend_admission.purpose)
    except ValueError as exc:
        raise EngineError(f"Range backend binding is not a closed policy value: {exc}") from exc
    admission = evaluate_gcp_backend_admission(backend, None, purpose)
    if not admission.admitted:
        raise EngineError(f"Range backend binding is not admitted by policy: {admission.reason}")
    return {"range_backend": backend, "instantiation_purpose": purpose.value}


def verify_existing_workspace_binding(
    existing_range: Range,
    request_id: UUID,
    workspace_id: int,
) -> None:
    """Reject an idempotent create replay whose workspace scope differs (ADR-046-R9).

    Engine create is idempotent on ``request_id``; a replay must carry the same
    tenancy scope the range was created with. A replay that names a *different*
    ``workspace_id`` is a cross-tenant binding conflict -- silently reusing the
    first range for the differently scoped replay would leak a range across
    workspaces -- so it is refused here rather than reused, exactly as a
    conflicting backend/participant/remote-access replay is. This is Engine's
    defense-in-depth half of the scope resolved and authorized by CMS; Engine
    still never resolves or authorizes a workspace itself (ADR-046-R1).
    """
    if existing_range.workspace_id != workspace_id:
        raise EngineError(
            f"Range workspace binding conflict for request {request_id}: persisted "
            f"workspace {existing_range.workspace_id} differs from requested workspace "
            f"{workspace_id} (ADR-046-R9 conflict; a scoped range is never silently reused)"
        )


# Range backends proven to realize the ADR-026 no-NAT ``none`` posture natively.
# The AWS path carries no GCP ``range_backend`` (it is ``None``) and realizes
# ``none`` through its Terraform route/NAT suppression; GCE realizes it by omitting
# the range-owned Cloud NAT. GDC (ADR-030) is excluded. A backend outside this set
# fails closed for a ``none`` launch rather than silently substituting its default
# egress behavior (PLAT-238 backend egress-capability gate, ADR-026-R6).
_EGRESS_NONE_CAPABLE_GCP_BACKENDS = frozenset({"gce"})


def assert_backend_supports_egress_none(range_backend: str | None, egress_mode: str) -> None:
    """Fail closed when a ``none`` range is bound to a backend without native no-NAT support.

    Called in the Engine create transaction with the resolved backend binding, so a
    zero-egress launch that landed on a backend that cannot prove no-NAT support is
    rejected before dispatch rather than silently getting that backend's default
    (possibly egress-capable) posture. ``None`` is the AWS path, which realizes
    ``none`` via its Terraform route suppression and is always capable.
    """
    if egress_mode != RangeEgressMode.NONE.value:
        return
    if range_backend is None:
        return
    if range_backend not in _EGRESS_NONE_CAPABLE_GCP_BACKENDS:
        raise EngineError(
            f"Range backend {range_backend!r} does not support the zero-egress ('none') posture; "
            "a backend must prove native no-NAT support before a none range is admitted (ADR-026-R6)"
        )


def egress_binding_fields(egress_mode: str) -> dict[str, str]:
    """Validate the pinned effective egress mode against the canonical vocabulary (PLAT-238).

    The mode is resolved and authorized by the CMS launch-admission seam under the
    workspace mutex (ADR-017-R5); Engine re-validates it is a closed
    ``RangeEgressMode`` value before persisting, so a fabricated or malformed mode
    from a refactored in-process caller can never be pinned on a range. Engine never
    resolves the workspace policy itself -- it only persists the value CMS decided.
    """
    try:
        mode = RangeEgressMode(egress_mode)
    except ValueError as exc:
        raise EngineError(f"Range egress mode is not a closed policy value: {exc}") from exc
    return {"egress_mode": mode.value}


def verify_existing_egress_binding(
    existing_range: Range,
    request_id: UUID,
    egress_mode: str,
) -> None:
    """Reject an idempotent create replay whose pinned egress mode differs (ADR-017-R5).

    Engine create is idempotent on ``request_id``; a replay must carry the same
    effective egress posture the range was pinned with. A replay that names a
    *different* mode is a decision conflict -- silently reusing the first range would
    let a re-resolved (and possibly weaker) posture attach to an already-provisioned
    range -- so it is refused rather than reused, exactly as a conflicting
    backend/workspace replay is. The pinned mode is authoritative; the deployment
    baseline is never re-consulted here (anti-pattern: deployment ``RANGE_EGRESS_MODE``
    must not override a pinned decision).
    """
    if existing_range.egress_mode != egress_mode:
        raise EngineError(
            f"Range egress binding conflict for request {request_id}: persisted "
            f"{existing_range.egress_mode!r} differs from requested {egress_mode!r} "
            f"(ADR-017-R5 conflict; a pinned egress decision is never silently re-resolved)"
        )


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
