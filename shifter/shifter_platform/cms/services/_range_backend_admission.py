"""GCP range-backend admission gate for the RAES launch path.

Issue #1354 generalized the gate from "always live-fire" to a trusted
instantiation purpose. The generic product facade still defaults to live-fire; a
dedicated non-user workflow supplies a closed :class:`InstantiationPurpose` to
opt in to the retained GDC plumbing (ADR-030-R3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cms.exceptions import CMSError
from shared.range_instantiation_policy import POLICY_DENIAL_CODE, InstantiationPurpose

if TYPE_CHECKING:
    from shared.enums import RangeSource
    from shared.range_instantiation_policy import BackendAdmission

logger = logging.getLogger(__name__)

_UNTRUSTED_PURPOSE = (
    "Range instantiation purpose must be a closed InstantiationPurpose value minted by a "
    "trusted server workflow. See ADR-030."
)

_CTF_IS_ALWAYS_LIVE_FIRE = (
    "CTF participant range creation is always live-fire and cannot request a non-user "
    "instantiation purpose. Kubernetes/GDC-backed participant infrastructure is not an "
    "approved containment boundary for CTF ranges. See ADR-030."
)


def _assert_trusted_purpose(purpose: object, range_source: RangeSource | None) -> InstantiationPurpose:
    """Validate the purpose as closed workflow authority for this launch source.

    A purpose is trusted server data. Rejecting a non-member (notably a raw
    string) keeps an untrusted value from being plumbed in as authority, and
    rejecting a non-live-fire purpose on a CTF launch keeps every CTF
    participant/batch/spare/recovery/scheduler path live-fire regardless of
    argument (ADR-030-R1/R6).
    """
    from shared.enums import RangeSource as _RangeSource

    if not isinstance(purpose, InstantiationPurpose):
        raise CMSError(_UNTRUSTED_PURPOSE, details={"code": POLICY_DENIAL_CODE})
    if range_source is _RangeSource.CTF and purpose is not InstantiationPurpose.LIVE_FIRE:
        logger.warning("create_range: non-user purpose refused for a CTF launch purpose=%s", purpose.value)
        raise CMSError(_CTF_IS_ALWAYS_LIVE_FIRE, details={"code": POLICY_DENIAL_CODE})
    return purpose


def assert_backend_admitted(
    purpose: object = InstantiationPurpose.LIVE_FIRE,
    range_source: RangeSource | None = None,
) -> BackendAdmission | None:
    """Reject a range launch on a backend not admitted for ``purpose`` (ADR-030).

    Used by every product path (Mission Control, CTF participant/batch/spare/
    recovery, management commands, and direct service callers) that funnels
    through the RAES launch facade. It runs before DB reservation, dispatch, subnet
    allocation, or any cloud mutation, and is a no-op for non-GCP providers.

    ``purpose`` is trusted workflow authority supplied by the calling server path,
    defaulting to live-fire. It is never derived from ``RangeSource``, scenario
    type, user role, ``ENVIRONMENT``, or the backend selector; ``range_source`` is
    consulted only to *refuse* non-user authority on a CTF launch. The closed
    policy and its default-deny backend registry live in
    ``shared.range_instantiation_policy``.

    Returns the admitted :class:`BackendAdmission` on GCP so the caller can carry
    the trusted (backend, purpose) to Engine persistence beside the spec (#1666);
    returns ``None`` for non-GCP providers. Raises ``CMSError`` on a denial.
    """
    import os

    from django.conf import settings

    from shared.range_instantiation_policy import evaluate_gcp_backend_admission

    trusted_purpose = _assert_trusted_purpose(purpose, range_source)
    if str(getattr(settings, "CLOUD_PROVIDER", "")).strip().lower() != "gcp":
        return None
    admission = evaluate_gcp_backend_admission(
        os.environ.get("GCP_RANGE_BACKEND"),
        os.environ.get("GCP_RANGE_PLANE"),
        trusted_purpose,
    )
    if not admission.admitted:
        logger.warning(
            "create_range: backend denied code=%s backend=%s purpose=%s",
            admission.code,
            admission.backend or "<unset>",
            trusted_purpose.value,
        )
        # Carry the stable ADR-039 classification (identity-or-policy vs prerequisite)
        # through CMSError.details so downstream retry/notification paths can treat a
        # permanent policy denial as non-retryable (issue #1348).
        raise CMSError(admission.reason, details={"code": admission.code})
    # Admitted: return the trusted result so the Engine binds backend/purpose from
    # the SAME evaluated value (never a second env read, which could race a
    # selector flip -- #1666 / preflight).
    return admission
