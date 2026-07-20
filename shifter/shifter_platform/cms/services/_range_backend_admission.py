"""Live-fire GCP range-backend admission gate (ADR-030 / #1348), returning its result (#1666).

The single service-level admission check shared by the cyberscript and ACES
create paths. Extracted from ``_range_create`` so that module stays within its
size budget; re-exported there for existing importers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.exceptions import CMSError

if TYPE_CHECKING:
    from shared.range_instantiation_policy import BackendAdmission

logger = logging.getLogger(__name__)


def _assert_live_fire_backend_admitted() -> BackendAdmission | None:
    """Reject a live-fire range launch on a non-approved GCP backend (ADR-030, #1348).

    Shared by ``create_range`` and ``create_aces_native_range`` -- and therefore
    every product path (Mission Control, CTF participant/batch/spare/recovery,
    ACES, management commands, and direct service callers) that funnels through
    them. It runs before the DB reservation, Engine persistence, dispatch, subnet
    allocation, or any cloud mutation, and is a no-op for non-GCP providers.
    ``RangeSource`` and ``ENVIRONMENT`` are never treated as approval; the closed
    policy lives in ``shared.range_instantiation_policy``.

    Returns the admitted :class:`BackendAdmission` on GCP so the caller can carry
    the trusted (backend, purpose) to Engine persistence beside the spec (#1666);
    returns ``None`` for non-GCP providers. Raises ``CMSError`` on a denial.
    """
    import os

    from django.conf import settings

    from shared.range_instantiation_policy import (
        InstantiationPurpose,
        evaluate_gcp_backend_admission,
    )

    if str(getattr(settings, "CLOUD_PROVIDER", "")).strip().lower() != "gcp":
        return None
    admission = evaluate_gcp_backend_admission(
        os.environ.get("GCP_RANGE_BACKEND"),
        os.environ.get("GCP_RANGE_PLANE"),
        InstantiationPurpose.LIVE_FIRE,
    )
    if not admission.admitted:
        logger.warning(
            "create_range: live-fire backend denied code=%s backend=%s",
            admission.code,
            admission.backend or "<unset>",
        )
        # Carry the stable ADR-039 classification (identity-or-policy vs prerequisite)
        # through CMSError.details so downstream retry/notification paths can treat a
        # permanent policy denial as non-retryable (issue #1348).
        raise CMSError(admission.reason, details={"code": admission.code})
    # Admitted: return the trusted result so the Engine binds backend/purpose from
    # the SAME evaluated value (never a second env read, which could race a
    # selector flip -- #1666 / preflight).
    return admission


def _openvpn_backend_admitted(backend_admission: BackendAdmission | None) -> bool:
    """Return whether the selected realization path implements OpenVPN v1.

    This is the trusted backend-capability admission seam for product launch
    code.  AWS and the admitted GCE range-cell backend implement the existing
    OpenVPN conformance contract.  Local provisioners and any other provider or
    backend remain capability-false even when they are otherwise allowed to
    launch a range.
    """
    from django.conf import settings

    if str(getattr(settings, "LOCAL_PROVISIONER", "")).strip():
        return False
    provider = str(getattr(settings, "CLOUD_PROVIDER", "")).strip().lower()
    if provider == "aws":
        return True
    return bool(
        provider == "gcp"
        and backend_admission is not None
        and backend_admission.admitted
        and backend_admission.backend == "gce"
    )
