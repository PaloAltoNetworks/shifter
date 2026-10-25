"""Closed image-candidate projection carried by a RAES operation generation.

Only resolver columns cross the Engine-to-provisioner boundary. Registry
management metadata and unbounded candidate collections fail at parse time.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from shared.raes.image_policy import validate_management_ssh_port, validate_management_ssh_username

from .operation_input_identity import (
    _KEY_SEPARATOR,
    RaesOperationInputError,
    _require,
    _require_exact_keys,
    _require_mapping,
)

MAX_IMAGE_CANDIDATES = 64
MAX_IMAGE_KEYS = 256

# Exactly the registry columns consumed by the resolver, including optional
# participant-host fields for a preconfigured machine image.
_CANDIDATE_KEYS = frozenset(
    {
        "source_version",
        "image_ref",
        "machine_type",
        "disk_size_gb",
        "disk_type",
        "management_ssh_port",
        "management_ssh_username",
        "image_kind",
        "bootstrap_capability",
        "participant_container_name",
        "participant_username",
        "participant_readiness_contract",
        "participant_readiness_manifest_sha256",
    }
)
_OPTIONAL_CANDIDATE_KEYS = frozenset(
    {
        "management_ssh_port",
        "management_ssh_username",
        "image_kind",
        "bootstrap_capability",
        "participant_container_name",
        "participant_username",
        "participant_readiness_contract",
        "participant_readiness_manifest_sha256",
    }
)


def _validate_host_fields(candidate: dict[str, Any], field: str) -> None:
    """Require a complete host contract only for a machine-image candidate."""
    image_kind = candidate.get("image_kind", "image")
    bootstrap = candidate.get("bootstrap_capability", "standard")
    if image_kind not in {"image", "machine-image"}:
        raise RaesOperationInputError(f"{field} image_kind is invalid")
    if not isinstance(bootstrap, str) or not bootstrap:
        raise RaesOperationInputError(f"{field} bootstrap_capability is invalid")
    _validate_participant_host_fields(candidate, field, bootstrap)
    if image_kind == "machine-image" and bootstrap != "preconfigured-machine-host":
        raise RaesOperationInputError(f"{field} machine-image requires a preconfigured host")


def _validate_participant_host_fields(candidate: dict[str, Any], field: str, bootstrap: str) -> None:
    """Validate the participant-facing portion of a candidate host contract."""
    participant_fields = (
        candidate.get("participant_container_name", ""),
        candidate.get("participant_username", ""),
        candidate.get("participant_readiness_contract", ""),
        candidate.get("participant_readiness_manifest_sha256", ""),
    )
    if not all(isinstance(value, str) for value in participant_fields):
        raise RaesOperationInputError(f"{field} participant host fields are invalid")
    if bootstrap == "preconfigured-machine-host" and not all(participant_fields):
        raise RaesOperationInputError(f"{field} preconfigured host fields are incomplete")
    if bootstrap != "preconfigured-machine-host" and any(participant_fields):
        raise RaesOperationInputError(f"{field} participant host fields require a preconfigured host")


def _validated_candidate(raw: object, field: str) -> dict[str, Any]:
    """Return one registry candidate row closed on exactly the resolver's columns."""
    candidate = _require_mapping(raw, field)
    _require_exact_keys(candidate, _CANDIDATE_KEYS, field, optional=_OPTIONAL_CANDIDATE_KEYS)
    if "management_ssh_port" in candidate:
        try:
            validate_management_ssh_port(candidate["management_ssh_port"])
        except ValueError as exc:
            raise RaesOperationInputError(f"{field}: {exc}") from None
    try:
        validate_management_ssh_username(candidate.get("management_ssh_username", ""))
    except ValueError as exc:
        raise RaesOperationInputError(f"{field}: {exc}") from None
    image_ref = candidate["image_ref"]
    if not isinstance(image_ref, str) or not image_ref.strip():
        raise RaesOperationInputError(f"{field} image_ref is invalid")
    _validate_host_fields(candidate, field)
    return candidate


def _validated_candidates(value: object) -> dict[str, tuple[dict[str, Any], ...]]:
    """Validate the ``(provider, source_name)``-keyed candidate projection."""
    raw = _require_mapping(value, "raes operation input image_candidates")
    _require(len(raw) <= MAX_IMAGE_KEYS, f"raes operation input carries more than {MAX_IMAGE_KEYS} image keys")

    projected: dict[str, tuple[dict[str, Any], ...]] = {}
    for key, rows in raw.items():
        _require(
            isinstance(key, str) and key.count(_KEY_SEPARATOR) == 1 and all(key.split(_KEY_SEPARATOR)),
            f"raes operation input image_candidates key '{key}' must be '<provider>:<source_name>'",
        )
        if not isinstance(rows, Sequence) or isinstance(rows, str | bytes):
            raise RaesOperationInputError(f"raes operation input image_candidates['{key}'] must be a list")
        entries = list(rows)
        _require(
            len(entries) <= MAX_IMAGE_CANDIDATES,
            f"raes operation input image_candidates['{key}'] carries more than {MAX_IMAGE_CANDIDATES} candidates",
        )
        projected[key] = tuple(
            _validated_candidate(entry, f"raes operation input image_candidates['{key}'][{index}]")
            for index, entry in enumerate(entries)
        )
    return projected
