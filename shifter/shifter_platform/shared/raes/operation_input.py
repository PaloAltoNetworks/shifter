"""Closed RAES operation-input contract (ADR-043 phase 5, #1837).

``shared.operation_envelope`` owns the *transport* shape; this module owns the
bounded ``payload`` the Engine materializes into ``OperationInput`` for an
``raes-range`` generation, and the fail-closed parser the provisioner runs
before any cloud or guest mutation.

It replaces four direct domain-table reads (``mission_control_range`` +
``engine_request`` for the plan, ``engine_raes_content_delivery_binding``,
``engine_raes_image_mapping``, and ``engine_instance`` for backend ownership
evidence) with one immutable row selected by the canonical ``operation_id``.

The projection *composes* existing contracts rather than re-modelling them:

* the serialized RAES ``ProvisioningPlan`` already persisted in ``range_config``
  and parsed by the provisioner's fail-closed ``raes_plan.parse_plan``;
* ``shared.raes.content_delivery.DeliveryBinding`` transport, byte-free;
* the registry candidate shape consumed by
  ``shared.raes.image_policy.resolve_from_candidates``; and
* the normalized backend vocabulary from ``shared.range_instantiation_policy``.

Deliberately absent: ``user_id`` and any payload-owned ownership, ORM joins,
raw ``engine_instance.state`` evidence, registry management metadata (primary
keys, ``enabled`` flags, notes, timestamps), disabled rows, and the tenant
registry as a whole. Ownership is the locked generation plus ``request_id``.

Dependency-light on purpose: the standalone provisioner image imports this
without Django or the platform schema graph.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from shared.model_access.guest_binding import ModelGuestBinding
from shared.raes.artifact_binding import MAX_ARTIFACT_BINDINGS, ArtifactBinding, ArtifactBindingError
from shared.raes.content_delivery import ContentDeliveryError, DeliveryBinding
from shared.raes.participant_access import (
    MAX_ACCESS_BINDINGS,
    ParticipantAccessBinding,
    ParticipantAccessError,
)
from shared.runtime_plugin_binding import RuntimePluginPin

from .operation_input_candidates import MAX_IMAGE_CANDIDATES, MAX_IMAGE_KEYS, _validated_candidates
from .operation_input_enrollment import _model_enrollments
from .operation_input_identity import (
    RaesOperationInputError,
    RaesRangeIdentity,
    _optional_str,
    _require,
    _require_exact_keys,
    _require_mapping,
    candidate_key,
    image_lookup_key,
    plan_image_lookup_keys,
)
from .operation_input_remote_access import RaesRemoteAccess, parse_remote_access

__all__ = [
    "MAX_ACCESS_BINDINGS",
    "MAX_ARTIFACT_BINDINGS",
    "MAX_DELIVERY_BINDINGS",
    "MAX_IMAGE_CANDIDATES",
    "MAX_IMAGE_KEYS",
    "RaesInputBindings",
    "RaesOperationInput",
    "RaesOperationInputError",
    "RaesRangeIdentity",
    "RaesRemoteAccess",
    "build_raes_operation_input",
    "candidate_key",
    "image_lookup_key",
    "parse_raes_operation_input",
    "plan_image_lookup_keys",
]


@dataclass(frozen=True)
class RaesInputBindings:
    """The byte-free binding identities that ride beside the plan in one input.

    Groups the three sidecar binding collections a RAES generation carries --
    content delivery (#1564), participant access (#1710), and generation-fenced
    artifacts (#1580) -- so the input builder takes one cohesive argument instead
    of three parallel ones. ``delivery`` is required; the other two default empty.
    """

    delivery: Sequence[DeliveryBinding]
    access: Sequence[ParticipantAccessBinding] = ()
    artifact: Sequence[ArtifactBinding] = ()
    runtime_plugin: RuntimePluginPin | None = None
    model_enrollments: tuple[ModelGuestBinding, ...] = ()
    remote_access: RaesRemoteAccess | None = None


# Bounded per ADR-043-R2/R7: the input is a reference-only projection, never a
# registry dump or a full topology snapshot.
MAX_DELIVERY_BINDINGS = 512

_INPUT_KEYS = frozenset(
    {
        "plan",
        "delivery_bindings",
        "access_bindings",
        "artifact_bindings",
        "image_candidates",
        "range_backend",
        "instantiation_purpose",
        "legacy_range_id",
        "egress_mode",
        "runtime_plugin",
        "model_enrollments",
        "resource_generation",
        "remote_access",
    }
)

# Optional for rolling-deploy compatibility (#1580 / codex review): a newer producer
# emits ``artifact_bindings`` only when a plan actually carries an artifact
# requirement, and a newer consumer tolerates its absence in an older queued input.
# The field is never required, so no OperationInput/envelope version bump is needed.
# Optional for rolling-deploy compatibility (PLAT-238, ADR-043 window): a newer
# producer always emits ``egress_mode``, but an older queued input minted before
# this deploy carries none. Absence resolves to ``status-quo`` (inherit the
# deployment baseline) -- the exact pre-feature behavior, never a silent
# *weakening*: a ``none`` zero-egress or an active egress posture is always carried
# explicitly, so a missing field can never be read as "allow egress".
# ``remote_access`` (#2030) is emitted only for a range holding an OpenVPN
# capability, so every other input stays byte-identical to the prior shape.
_OPTIONAL_INPUT_KEYS = frozenset(
    {"artifact_bindings", "egress_mode", "runtime_plugin", "model_enrollments", "resource_generation", "remote_access"}
)

# Mirrors ``installation.range_egress.RangeEgressMode`` without importing it (the
# provisioner image does not load the installation/pydantic machinery, exactly as
# ``_VALID_RANGE_BACKENDS`` mirrors the backend vocabulary). Closed here so an
# unknown egress mode fails at the wire.
_VALID_EGRESS_MODES = frozenset({"status-quo", "deny-all", "allowlist", "none"})
_DEFAULT_EGRESS_MODE = "status-quo"

# Mirrors ``shared.range_instantiation_policy`` without importing it: that module
# pulls settings/policy machinery the provisioner image does not load. The
# vocabulary is closed here so an unknown backend fails at the wire.
_VALID_RANGE_BACKENDS = frozenset({"gce", "gdc", "ec2"})


@dataclass(frozen=True)
class RaesOperationInput:
    """The parsed, validated RAES input for one operation generation."""

    plan: dict[str, Any]
    delivery_bindings: tuple[DeliveryBinding, ...]
    access_bindings: tuple[ParticipantAccessBinding, ...]
    artifact_bindings: tuple[ArtifactBinding, ...]
    range_backend: str | None
    instantiation_purpose: str | None
    legacy_range_id: int
    egress_mode: str
    _image_candidates: dict[str, tuple[dict[str, Any], ...]]
    runtime_plugin: RuntimePluginPin | None = None
    model_enrollments: tuple[ModelGuestBinding, ...] = ()
    resource_generation: str | None = None
    remote_access: RaesRemoteAccess | None = None

    def artifact_binding_for(self, target: str) -> ArtifactBinding | None:
        """Return the fenced artifact binding for a node address, or None.

        A binding means the Engine resolved an authored artifact requirement to a
        concrete backend image at launch; the provisioner realizes exactly that
        image and never re-resolves. ``None`` means the node had no artifact
        requirement and the legacy source-alias resolution applies.
        """
        for binding in self.artifact_bindings:
            if binding.target == target:
                return binding
        return None

    def image_candidates_for(self, provider: str, source_name: str) -> list[dict[str, Any]]:
        """Return the projected registry candidates for one lookup key.

        An empty list means the projection carried no enabled row for that key.
        That is a resolver concern -- the existing image policy fails loud at
        realization -- not a transport error.
        """
        return [dict(candidate) for candidate in self._image_candidates.get(candidate_key(provider, source_name), ())]

    def binding_transport(self) -> list[dict[str, Any]]:
        """Return the byte-free binding transport rows for the realization path."""
        return [binding.to_transport() for binding in self.delivery_bindings]

    def access_binding_transport(self) -> list[dict[str, Any]]:
        """Return the non-secret participant-access rows for the realization path."""
        return [binding.to_transport() for binding in self.access_bindings]


def _validated_egress_mode(value: object) -> str:
    """Return the pinned effective egress mode, defaulting an absent field to status-quo.

    A ``None`` (absent key) is an older queued input from before this deploy; it
    resolves to ``status-quo`` -- inherit the deployment baseline -- which is the
    exact pre-feature behavior and never a silent weakening (a ``none`` or active
    posture is always carried explicitly). A *present but unrecognized* value fails
    closed at the wire rather than being coerced, so a tampered input cannot smuggle
    an unknown posture past the boundary.
    """
    if value is None:
        return _DEFAULT_EGRESS_MODE
    _require(isinstance(value, str) and value in _VALID_EGRESS_MODES, "raes operation input egress_mode is invalid")
    return str(value)


def _validated_backend(value: object) -> str | None:
    """Return a normalized range backend, or None when the range carries no binding."""
    if value is None:
        return None
    _require(isinstance(value, str), "raes operation input range_backend must be a string or null")
    _require(
        value in _VALID_RANGE_BACKENDS,
        f"raes operation input range_backend must be one of: {', '.join(sorted(_VALID_RANGE_BACKENDS))}",
    )
    return str(value)


def _validated_legacy_range_id(value: object) -> int:
    """Return the opaque legacy naming key, or fail closed.

    This integer reconstructs deterministic cloud-resource and secret names that
    RAES already derives from ``Range.id``. It is never used to select or
    authorize an Engine row -- ``request_id`` plus the locked generation do that.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise RaesOperationInputError("raes operation input legacy_range_id must be an int")
    if value <= 0:
        raise RaesOperationInputError("raes operation input legacy_range_id must be positive")
    return value


def _validated_bindings(value: object) -> tuple[DeliveryBinding, ...]:
    """Rebuild every delivery binding through its own closed parser."""
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise RaesOperationInputError("raes operation input delivery_bindings must be a list")
    rows = list(value)
    _require(
        len(rows) <= MAX_DELIVERY_BINDINGS,
        f"raes operation input carries more than {MAX_DELIVERY_BINDINGS} delivery bindings",
    )
    bindings: list[DeliveryBinding] = []
    for index, row in enumerate(rows):
        raw = _require_mapping(row, f"raes operation input delivery_bindings[{index}]")
        try:
            # DeliveryBinding.from_transport is the gate: it rejects unknown keys,
            # so a smuggled bucket / URL / signed-URL / bytes field cannot ride
            # along, and it re-validates the digest, key, and byte count.
            bindings.append(DeliveryBinding.from_transport(raw))
        except ContentDeliveryError as exc:
            raise RaesOperationInputError(f"raes operation input delivery_bindings[{index}]: {exc}") from None
    return tuple(bindings)


def _validated_access_bindings(value: object) -> tuple[ParticipantAccessBinding, ...]:
    """Rebuild every participant-access binding through its own closed parser.

    ``ParticipantAccessBinding.from_transport`` is the gate: it rejects unknown
    keys, so a smuggled address, port, login name, or credential reference
    cannot ride along, and it re-validates the channel vocabulary and every
    compiled identity. A duplicate ``(target, channel)`` is rejected here because
    the sidecar is the declaration of record the realized access is compared
    against (ADR-032-R10).
    """
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise RaesOperationInputError("raes operation input access_bindings must be a list")
    rows = list(value)
    _require(
        len(rows) <= MAX_ACCESS_BINDINGS,
        f"raes operation input carries more than {MAX_ACCESS_BINDINGS} access bindings",
    )
    bindings: list[ParticipantAccessBinding] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        raw = _require_mapping(row, f"raes operation input access_bindings[{index}]")
        try:
            binding = ParticipantAccessBinding.from_transport(raw)
        except ParticipantAccessError as exc:
            raise RaesOperationInputError(f"raes operation input access_bindings[{index}]: {exc}") from None
        endpoint = (binding.target_address, binding.channel)
        _require(
            endpoint not in seen,
            f"raes operation input access_bindings[{index}] duplicates {binding.target_address}/{binding.channel}",
        )
        seen.add(endpoint)
        bindings.append(binding)
    return tuple(bindings)


def _validated_artifact_bindings(value: object) -> tuple[ArtifactBinding, ...]:
    """Rebuild every fenced artifact binding through its own closed parser.

    ``ArtifactBinding.from_transport`` is the gate: it rejects unknown keys, so a
    smuggled credential, URL, or byte payload cannot ride along, and it
    re-validates the digest, acquisition, and timing vocabulary. A duplicate
    ``target`` is rejected because the provisioner resolves one binding per node,
    and a second binding for the same node is ambiguous.
    """
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise RaesOperationInputError("raes operation input artifact_bindings must be a list")
    rows = list(value)
    _require(
        len(rows) <= MAX_ARTIFACT_BINDINGS,
        f"raes operation input carries more than {MAX_ARTIFACT_BINDINGS} artifact bindings",
    )
    bindings: list[ArtifactBinding] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        raw = _require_mapping(row, f"raes operation input artifact_bindings[{index}]")
        try:
            binding = ArtifactBinding.from_transport(raw)
        except ArtifactBindingError as exc:
            raise RaesOperationInputError(f"raes operation input artifact_bindings[{index}]: {exc}") from None
        _require(
            binding.target not in seen,
            f"raes operation input artifact_bindings[{index}] duplicates target {binding.target}",
        )
        seen.add(binding.target)
        bindings.append(binding)
    return tuple(bindings)


def parse_raes_operation_input(payload: object) -> RaesOperationInput:
    """Validate an RAES operation-input payload and return the parsed projection.

    Fails closed on an unexpected or missing key, a non-mapping payload, a
    tampered or over-claiming delivery binding, an unbounded collection, a
    registry row carrying management metadata, a malformed candidate key, an
    unknown backend, or a non-positive legacy naming key.
    """
    obj = _require_mapping(payload, "raes operation input")
    _require_exact_keys(obj, _INPUT_KEYS, "raes operation input", optional=_OPTIONAL_INPUT_KEYS)
    plugin = None
    if "runtime_plugin" in obj:
        try:
            plugin = RuntimePluginPin.model_validate(obj["runtime_plugin"])
            plugin.bindings.validate_plan(obj["plan"])
        except ValueError:
            raise RaesOperationInputError("raes operation input runtime plugin binding is invalid") from None
    resource_generation = obj.get("resource_generation")
    if resource_generation is not None or obj["range_backend"] == "ec2":
        try:
            valid_epoch = isinstance(resource_generation, str) and str(UUID(resource_generation)) == resource_generation
        except ValueError:
            valid_epoch = False
        _require(valid_epoch, "raes operation input resource generation is missing or invalid")
    access_bindings = _validated_access_bindings(obj["access_bindings"])
    remote_access = parse_remote_access(obj["remote_access"]) if "remote_access" in obj else None
    _require(
        remote_access is None
        or remote_access.target_ref in {f"{binding.target_address}#0" for binding in access_bindings},
        "raes operation input remote access target is not a declared participant-access target",
    )
    return RaesOperationInput(
        plan=_require_mapping(obj["plan"], "raes operation input plan"),
        delivery_bindings=_validated_bindings(obj["delivery_bindings"]),
        access_bindings=access_bindings,
        artifact_bindings=_validated_artifact_bindings(obj.get("artifact_bindings", [])),
        range_backend=_validated_backend(obj["range_backend"]),
        instantiation_purpose=_optional_str(obj["instantiation_purpose"]),
        legacy_range_id=_validated_legacy_range_id(obj["legacy_range_id"]),
        egress_mode=_validated_egress_mode(obj.get("egress_mode")),
        _image_candidates=_validated_candidates(obj["image_candidates"]),
        runtime_plugin=plugin,
        model_enrollments=_model_enrollments(obj, plugin),
        resource_generation=resource_generation,
        remote_access=remote_access,
    )


def build_raes_operation_input(
    *,
    plan: Mapping[str, Any],
    bindings: RaesInputBindings,
    image_candidates: Mapping[str, Sequence[Mapping[str, Any]]],
    range_backend: str | None,
    instantiation_purpose: str | None,
    identity: RaesRangeIdentity,
    egress_mode: str = _DEFAULT_EGRESS_MODE,
) -> dict[str, Any]:
    """Compose and validate the RAES operation-input payload in one step.

    Returns the JSON-serialisable payload for ``build_operation_envelope``.
    Candidate sets are emitted in sorted key order so the same generation
    materializes byte-identical input on a retry. ``egress_mode`` is the effective
    range egress posture pinned at create (PLAT-238); a newer producer always emits
    it so the provisioner realizes it from the input rather than the deployment env.
    """
    payload = {
        "plan": dict(plan),
        "delivery_bindings": [binding.to_transport() for binding in bindings.delivery],
        "access_bindings": [binding.to_transport() for binding in bindings.access],
        "image_candidates": {key: [dict(row) for row in image_candidates[key]] for key in sorted(image_candidates)},
        "range_backend": range_backend,
        "instantiation_purpose": instantiation_purpose,
        "legacy_range_id": identity.legacy_range_id,
        "egress_mode": egress_mode,
    }
    # Emit artifact_bindings only when a plan actually carries an artifact
    # requirement, so the common no-requirement input is byte-identical to the
    # pre-#1580 shape and an older consumer never sees an unexpected key.
    if bindings.artifact:
        payload["artifact_bindings"] = [binding.to_transport() for binding in bindings.artifact]
    if bindings.runtime_plugin is not None:
        payload["runtime_plugin"] = bindings.runtime_plugin.model_dump(mode="json")
    if bindings.model_enrollments:
        payload["model_enrollments"] = [row.model_dump(mode="json") for row in bindings.model_enrollments]
    if identity.resource_generation is not None:
        payload["resource_generation"] = identity.resource_generation
    if bindings.remote_access is not None:
        payload["remote_access"] = bindings.remote_access.to_transport()
    parse_raes_operation_input(payload)
    return payload
