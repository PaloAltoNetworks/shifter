"""Closed range-instantiation policy: which range backend is admitted for which launch purpose.

ADR-030 decides the containment boundary: normal Shifter scenarios (Mission
Control and CTF) are live-fire, and the GDC VM Runtime backend is not an approved
live-fire participant boundary. Normal GCP ranges may realize only on the
approved GCE VM range-cell backend; the retained Kubernetes/GDC substrate is
reachable only from an explicitly declared non-user mode (issues #1348, #1354).

This module is the single, Django-free policy seam shared by the CMS service gate
(primary admission, before reservation/dispatch), the Engine binding writer, and
the provisioner (defense-in-depth denial). It is intentionally dependency-light so
the standalone provisioner and Django both import it, exactly as they both import
``shared.range_cells``. It holds the *one* GCP range-backend parser so CMS,
Engine, the provisioner, renderers, and tests never reproduce the ``gce``/``gdc``
string validation independently.

:data:`RANGE_BACKENDS` is the sole registration surface (ADR-030-R6): a backend
is admitted for a purpose only when that purpose is explicitly enumerated in its
registration. Registration is default-deny -- a backend added without a permitted
purpose can launch nothing. See
``docs/technical/platform_infrastructure/range-instantiation-policy.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

_DEFAULT_GCP_RANGE_BACKEND = "gce"
_GCP_PROVIDER = "gcp"

# ADR-039 failure classes reused for policy denials (issue #1348).
# ``identity-or-policy`` is a permanent authorization denial (must not be
# retried); ``prerequisite`` means the required approved-backend configuration is
# missing or malformed (fail closed -- never permission to fall back to GDC).
POLICY_DENIAL_CODE = "identity-or-policy"
PREREQUISITE_DENIAL_CODE = "prerequisite"
UNSUPPORTED_CAPABILITY_CODE = "unsupported-capability"

# ADR-030-R3: a denial must name the scope the retained substrate is limited to,
# so deterministic demo infrastructure is never mistaken for the approved
# live-fire range backend.
_APPROVED_SCOPE_NOTE = (
    "Only the GCE VM range-cell backend is approved for live-fire ranges "
    "(set GCP_RANGE_BACKEND=gce); the retained GDC VM Runtime substrate is limited to the "
    "non-user demo/BAS and operator-validation modes named by ADR-030."
)


class InstantiationPurpose(StrEnum):
    """Closed set of trusted launch purposes bound at admission time.

    ``LIVE_FIRE`` is every normal Mission Control / CTF range: participants and
    agents run arbitrary activity, so only an approved containment backend is
    admitted. An ordinary Mission Control demo scenario is still live-fire
    (ADR-030-R6).

    The non-user purposes are the modes ADR-030-R3 names. ``NON_USER_DEMO`` is a
    deterministic product demo or breach-and-attack-simulation launch;
    ``OPERATOR_VALIDATION`` is operator-run or image-build validation of the
    substrate itself. Neither carries participant workload.

    ``NON_USER_VALIDATION`` is the original undifferentiated non-user value from
    issue #1348. It is retained so rows already persisted under it (including via
    ``manage.py backfill_range_backend_binding --purpose``) keep parsing; new
    trusted workflows must mint one of the two specific purposes instead.

    A purpose is trusted workflow authority. It is never derived from
    ``RangeSource``, scenario type or id, user role, ``ENVIRONMENT``,
    ``CLOUD_PROVIDER``, feature flags, or the ``GCP_RANGE_BACKEND`` selector.
    """

    LIVE_FIRE = "live_fire"
    NON_USER_DEMO = "non_user_demo"
    OPERATOR_VALIDATION = "operator_validation"
    NON_USER_VALIDATION = "non_user_validation"


@dataclass(frozen=True)
class RangeBackendRegistration:
    """One registered range-instantiation backend and the purposes it may serve.

    ``slug`` is the canonical backend identifier (the value persisted in
    ``engine.models.Range.range_backend`` and parsed from ``GCP_RANGE_BACKEND``).
    ``provider`` associates it with a deployment provider bundle. Adding a
    substrate to an existing provider belongs here, not in
    ``installation.registry.BACKEND_BUNDLES``, which registers cloud providers.

    ``permitted_purposes`` is enumerated explicitly and is never derived from
    "all enum members", environment, or maturity. An empty set means the backend
    is registered but not yet approved to launch anything.
    """

    slug: str
    provider: str
    permitted_purposes: frozenset[InstantiationPurpose]
    #: Whether this backend implements the optional ``range-warm-activation/v1``
    #: capability (ADR-039-R11, #28): warm-prepare a system-owned quarantined
    #: generation and later ``activate`` it for a claimant with fresh, fully
    #: sanitized access. Enumerated per backend, never inferred from the provider
    #: name. A backend with ``False`` safely never yields a warm claim -- the
    #: launch path falls back to cold provisioning before any warm mutation.
    warm_activation: bool = False


# The single registration surface (ADR-030-R6). GCE range cells are the approved
# live-fire containment boundary and may also serve every non-user mode. GDC VM
# Runtime is retained plumbing: it may serve only the non-user modes ADR-030-R3
# names, and can never be selected for live fire.
RANGE_BACKENDS: Mapping[str, RangeBackendRegistration] = MappingProxyType(
    {
        "gce": RangeBackendRegistration(
            "gce",
            _GCP_PROVIDER,
            # Enumerated, never ``frozenset(InstantiationPurpose)``: deriving the set
            # from "all enum members" would silently admit every future purpose on
            # this backend without a backend-policy decision (ADR-030-R6).
            frozenset(
                {
                    InstantiationPurpose.LIVE_FIRE,
                    InstantiationPurpose.NON_USER_DEMO,
                    InstantiationPurpose.OPERATOR_VALIDATION,
                    InstantiationPurpose.NON_USER_VALIDATION,
                }
            ),
            # GCE range cells are the only backend with a warm-activation adapter
            # today (#28). AWS (legacy user_id-bearing intent) and GDC advertise it
            # unsupported and cold-fall-back until their ownership-neutral
            # realization exists (AWS: #2069).
            warm_activation=True,
        ),
        "gdc": RangeBackendRegistration(
            "gdc",
            _GCP_PROVIDER,
            frozenset(
                {
                    InstantiationPurpose.NON_USER_DEMO,
                    InstantiationPurpose.OPERATOR_VALIDATION,
                    InstantiationPurpose.NON_USER_VALIDATION,
                }
            ),
        ),
    }
)

# Derived from the registry so the selector parser and the admission matrix
# cannot drift: an unregistered slug is unparseable, and therefore unselectable.
_VALID_GCP_RANGE_BACKENDS = frozenset(
    slug for slug, registration in RANGE_BACKENDS.items() if registration.provider == _GCP_PROVIDER
)


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
        registered = "' or '".join(sorted(_VALID_GCP_RANGE_BACKENDS))
        raise GcpRangeBackendError(f"GCP_RANGE_BACKEND must be '{registered}', got {candidate!r}")
    return candidate


def parse_instantiation_purpose(raw: str | None) -> InstantiationPurpose:
    """Return the closed purpose for a persisted or configured value.

    A blank or absent value is the legacy pre-#1666 / non-GCP sentinel and parses
    as :attr:`InstantiationPurpose.LIVE_FIRE` -- the strictest interpretation of
    "no recorded purpose", so an unbound row can never obtain non-user authority.
    An unrecognized value raises :class:`ValueError`; callers map that to their own
    ``prerequisite`` diagnostic rather than guessing.
    """
    candidate = (raw or "").strip().lower()
    if not candidate:
        return InstantiationPurpose.LIVE_FIRE
    try:
        return InstantiationPurpose(candidate)
    except ValueError as exc:
        valid = ", ".join(purpose.value for purpose in InstantiationPurpose)
        raise ValueError(f"instantiation purpose must be one of: {valid}; got {candidate!r}") from exc


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


def _denial_reason(registration: RangeBackendRegistration, purpose: InstantiationPurpose) -> str:
    """Return the authored, stable reason for a denied (backend, purpose) pair.

    Names the denied pair and the backend's registered scope (ADR-030-R3) without
    echoing configuration, secrets, or raw exception text.
    """
    permitted = ", ".join(sorted(p.value for p in registration.permitted_purposes)) or "no purpose"
    return (
        f"Range backend '{registration.slug}' is not admitted for instantiation purpose "
        f"'{purpose.value}'. It is registered for: {permitted}. {_APPROVED_SCOPE_NOTE}"
    )


def evaluate_gcp_backend_admission(
    raw_backend: str | None,
    raw_plane: str | None,
    purpose: InstantiationPurpose,
) -> BackendAdmission:
    """Evaluate whether the selected GCP range backend is admitted for ``purpose``.

    Fail-closed and default-deny (ADR-030-R6): an unknown, blank-invalid, or
    unregistered selector is a ``prerequisite`` denial, never permission to fall
    back to GDC. A registered backend admits only the purposes its
    :data:`RANGE_BACKENDS` entry enumerates; anything else is a permanent
    ``identity-or-policy`` denial. Selecting ``gdc`` for a live-fire launch is
    therefore denied, while an explicitly declared non-user mode may use the
    retained substrate.
    """
    try:
        backend = normalize_gcp_range_backend(raw_backend, raw_plane)
    except GcpRangeBackendError as exc:
        return BackendAdmission(False, "", purpose, PREREQUISITE_DENIAL_CODE, str(exc))

    # normalize_gcp_range_backend's valid set is derived from RANGE_BACKENDS, so a
    # parsed slug is always registered.
    registration = RANGE_BACKENDS[backend]
    if purpose in registration.permitted_purposes:
        return BackendAdmission(True, backend, purpose, "", "")
    return BackendAdmission(False, backend, purpose, POLICY_DENIAL_CODE, _denial_reason(registration, purpose))


def backend_supports_warm_activation(backend: str | None) -> bool:
    """Return whether ``backend`` advertises the ``range-warm-activation/v1`` capability.

    The single capability lookup (#28, ADR-039-R11). An unknown or unregistered
    backend is ``False``: warm activation is capability evidence from the registry,
    never inferred, so an unrecognized value fails closed to the cold path.
    """
    if not backend:
        return False
    registration = RANGE_BACKENDS.get(backend.strip().lower())
    return bool(registration and registration.warm_activation)
