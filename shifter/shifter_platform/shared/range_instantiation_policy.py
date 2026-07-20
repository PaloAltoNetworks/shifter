"""Closed range-instantiation policy: which GCP range backend is admitted for which launch purpose.

ADR-030 decides the containment boundary: normal Shifter scenarios (Mission
Control and CTF) are live-fire, and the GDC VM Runtime backend is not an approved
live-fire participant boundary. Normal GCP ranges may realize only on the
approved GCE VM range-cell backend; GDC VM Runtime is development/validation only
(issue #1348).

This module is the single, Django-free policy seam shared by the CMS service gate
(primary admission, before reservation/dispatch) and the provisioner
(defense-in-depth denial). It is intentionally dependency-light so the standalone
provisioner and Django both import it, exactly as they both import
``shared.range_cells``. It holds the *one* GCP range-backend parser so CMS,
Engine, the provisioner, renderers, and tests never reproduce the ``gce``/``gdc``
string validation independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_DEFAULT_GCP_RANGE_BACKEND = "gce"
_VALID_GCP_RANGE_BACKENDS = frozenset({"gce", "gdc"})
_SUPPORTED_LIVE_FIRE_BACKEND = "gce"

# ADR-039 failure classes reused for policy denials (issue #1348).
# ``identity-or-policy`` is a permanent authorization denial (must not be
# retried); ``prerequisite`` means the required approved-backend configuration is
# missing or malformed (fail closed -- never permission to fall back to GDC).
POLICY_DENIAL_CODE = "identity-or-policy"
PREREQUISITE_DENIAL_CODE = "prerequisite"

_LIVE_FIRE_GDC_REASON = (
    "GDC VM Runtime is not an approved live-fire range backend. Normal GCP ranges "
    "must use the GCE VM range-cell backend (set GCP_RANGE_BACKEND=gce). "
    "GDC VM Runtime is development/validation only. See ADR-030."
)


class InstantiationPurpose(StrEnum):
    """Closed set of trusted launch purposes bound at admission time.

    ``LIVE_FIRE`` is every normal Mission Control / CTF range: participants and
    agents run arbitrary activity, so only an approved containment backend is
    admitted. ``NON_USER_VALIDATION`` is the retained operator/dev validation path
    for the GDC substrate (no user workload); it is not reachable from any generic
    product range command today (#1354 owns the durable expansion). The purpose is
    orthogonal to ``RangeSource``, ``ENVIRONMENT``, ``CLOUD_PROVIDER``, and
    scenario type.
    """

    LIVE_FIRE = "live_fire"
    NON_USER_VALIDATION = "non_user_validation"


class GcpRangeBackendError(ValueError):
    """Raised when a GCP range backend selector value is not a known backend."""


def normalize_gcp_range_backend(raw_backend: str | None, raw_plane: str | None = None) -> str:
    """Return the normalized GCP range backend from the selector plus compat alias.

    First non-empty of ``GCP_RANGE_BACKEND`` then the ``GCP_RANGE_PLANE`` alias,
    stripped and lower-cased, defaulting to ``gce``. Raises
    :class:`GcpRangeBackendError` for any other (including whitespace-only) value.
    This is the single parser; do not reproduce it.
    """
    raw = raw_backend or raw_plane or _DEFAULT_GCP_RANGE_BACKEND
    candidate = raw.strip().lower()
    if candidate not in _VALID_GCP_RANGE_BACKENDS:
        raise GcpRangeBackendError(f"GCP_RANGE_BACKEND must be 'gdc' or 'gce', got {candidate!r}")
    return candidate


@dataclass(frozen=True)
class BackendAdmission:
    """Result of evaluating a (backend, purpose) pair against the closed policy.

    ``code`` is empty when admitted; otherwise one of :data:`POLICY_DENIAL_CODE`
    or :data:`PREREQUISITE_DENIAL_CODE`. ``reason`` is an authored, stable message
    safe to surface (no secrets, no raw exception text). Callers map this to their
    own error envelope (``CMSError``, ``CloudError``) rather than sharing an
    exception hierarchy.
    """

    admitted: bool
    backend: str
    purpose: InstantiationPurpose
    code: str
    reason: str


def evaluate_gcp_backend_admission(
    raw_backend: str | None,
    raw_plane: str | None,
    purpose: InstantiationPurpose,
) -> BackendAdmission:
    """Evaluate whether the selected GCP range backend is admitted for ``purpose``.

    Fail-closed: an unknown, blank-invalid, or malformed selector is a
    ``prerequisite`` denial, never permission to fall back to GDC. A live-fire
    launch admits only ``gce``; an explicit ``gdc`` selection for live-fire is a
    permanent ``identity-or-policy`` denial. Non-user validation may use the
    retained ``gdc`` substrate.
    """
    try:
        backend = normalize_gcp_range_backend(raw_backend, raw_plane)
    except GcpRangeBackendError as exc:
        return BackendAdmission(False, "", purpose, PREREQUISITE_DENIAL_CODE, str(exc))

    # Non-user validation may use either substrate; a live-fire launch admits only
    # the approved GCE backend. A single admitted/denied tail keeps this within the
    # 3-return limit (Sonar python:S1142).
    admitted = purpose is InstantiationPurpose.NON_USER_VALIDATION or backend == _SUPPORTED_LIVE_FIRE_BACKEND
    if admitted:
        return BackendAdmission(True, backend, purpose, "", "")
    return BackendAdmission(False, backend, purpose, POLICY_DENIAL_CODE, _LIVE_FIRE_GDC_REASON)
