"""Shared-native validation contract for ACES package-source catalog records.

ACES package-source rows are *provenance-only*. They reference an authored ACES
package (path/key + version + digest), its lock artifact, the contract/profile
the package claims, bounded provenance, and a conformance status/report ref.
They MUST NOT carry raw ACES SDL, imported module bodies, generated content,
hydrated runtime specs, flags, credentials, tokens, or runtime config.

This module is pure (stdlib only) so it can validate at the model boundary
without importing Django or ``cms``. See
``docs/architecture/aces-package-source-catalog-preflight-1252.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Bounded JSON value types allowed inside provenance.
Scalar = str | int | float | bool | None
ProvenanceValue = Scalar | list[Scalar]
Provenance = dict[str, ProvenanceValue]

# Extensible allowlists — the data-driven discriminator seam (repo vs
# object-backed source; the ACES contract kind; conformance readiness). Widen
# these module constants, not the call sites, when a new source or profile lands.
SOURCE_KINDS = frozenset({"repo", "object"})
CONTRACT_KINDS = frozenset({"aces"})
CONFORMANCE_STATUSES = frozenset({"pending", "passed", "failed"})

# Provenance is an *allowlist* of bounded reference keys. Anything else — sdl,
# module bodies, generated content, credentials, tokens, runtime config — is
# rejected by construction rather than by a fragile denylist.
PROVENANCE_KEYS = frozenset(
    {
        "repo",
        "commit",
        "ref",
        "tool",
        "tool_version",
        "conformance_report",
        "generated_at",
        "notes",
    }
)

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_REF_LEN = 512
_MAX_PROVENANCE_BYTES = 4096
_MAX_PROVENANCE_VALUE_LEN = 512
_MAX_PROVENANCE_LIST_LEN = 32
_FORBIDDEN_CHARS = ("\n", "\r", "\x00")


class AcesPackageSourceError(ValueError):
    """Raised when a package-source record violates the provenance-only contract."""


@dataclass(frozen=True)
class PackageSourceRecord:
    """Immutable bundle of package-source fields to validate as one unit.

    Grouping the fields keeps the validator's signature to a single argument
    and gives every field an explicit type.
    """

    source_kind: str
    contract_kind: str
    contract_profile: str
    package_ref: str
    package_version: str
    package_digest: str
    conformance_status: str
    lock_ref: str = ""
    lock_digest: str = ""
    conformance_report_ref: str = ""
    provenance: object = None


def _require_single_line_ref(name: str, value: object, *, required: bool) -> None:
    """Reject a reference that is missing (when required), too long, or multi-line."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise AcesPackageSourceError(f"{name} must be a string")
    if not value.strip():
        if required:
            raise AcesPackageSourceError(f"{name} is required")
        return
    if len(value) > _MAX_REF_LEN:
        raise AcesPackageSourceError(f"{name} exceeds {_MAX_REF_LEN} characters")
    if any(ch in value for ch in _FORBIDDEN_CHARS):
        raise AcesPackageSourceError(f"{name} must be a single-line reference, not embedded content")


def _require_digest(name: str, value: object, *, required: bool) -> None:
    """Reject a digest that is missing (when required) or not ``sha256:<64 hex>``."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise AcesPackageSourceError(f"{name} must be a string")
    if not value:
        if required:
            raise AcesPackageSourceError(f"{name} is required")
        return
    if not _DIGEST_RE.match(value):
        raise AcesPackageSourceError(f"{name} must be a 'sha256:<64 hex>' digest")


def _validate_scalar(key: str, value: object) -> None:
    """Reject a provenance value that is not a bounded, single-line scalar."""
    # bool is a subclass of int; treat it (and None/int/float) as allowed scalars.
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > _MAX_PROVENANCE_VALUE_LEN:
            raise AcesPackageSourceError(f"provenance '{key}' value exceeds {_MAX_PROVENANCE_VALUE_LEN} characters")
        if any(ch in value for ch in _FORBIDDEN_CHARS):
            raise AcesPackageSourceError(f"provenance '{key}' value must be single-line, not embedded content")
        return
    raise AcesPackageSourceError(f"provenance '{key}' value must be a scalar or list of scalars")


def _require_provenance_size(provenance: dict[str, object]) -> None:
    """Reject provenance whose serialized JSON exceeds the byte cap."""
    try:
        encoded = json.dumps(provenance)
    except (TypeError, ValueError) as exc:
        raise AcesPackageSourceError("provenance must be JSON-serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_PROVENANCE_BYTES:
        raise AcesPackageSourceError(f"provenance exceeds {_MAX_PROVENANCE_BYTES} bytes")


def _require_provenance_entry(key: object, value: object) -> None:
    """Reject a provenance entry with a non-allowlisted key or an invalid value."""
    if not isinstance(key, str):
        raise AcesPackageSourceError("provenance keys must be strings")
    if key not in PROVENANCE_KEYS:
        raise AcesPackageSourceError(f"provenance key '{key}' is not an allowed reference key")
    if isinstance(value, list):
        if len(value) > _MAX_PROVENANCE_LIST_LEN:
            raise AcesPackageSourceError(f"provenance '{key}' list exceeds {_MAX_PROVENANCE_LIST_LEN} items")
        for item in value:
            _validate_scalar(key, item)
        return
    _validate_scalar(key, value)


def _validate_provenance(provenance: object) -> Provenance:
    """Validate bounded provenance: allowlisted keys, scalar/list values, size cap."""
    if provenance is None:
        return {}
    if not isinstance(provenance, dict):
        raise AcesPackageSourceError("provenance must be a JSON object")
    _require_provenance_size(provenance)
    for key, value in provenance.items():
        _require_provenance_entry(key, value)
    return provenance


def validate_package_source(record: PackageSourceRecord) -> Provenance:
    """Validate a package-source record against the provenance-only contract.

    Raises:
        AcesPackageSourceError: on any violation.

    Returns:
        The validated provenance dict (``{}`` when ``record.provenance`` is ``None``).
    """
    if record.source_kind not in SOURCE_KINDS:
        raise AcesPackageSourceError(f"source_kind must be one of {sorted(SOURCE_KINDS)}")
    if record.contract_kind not in CONTRACT_KINDS:
        raise AcesPackageSourceError(f"contract_kind must be one of {sorted(CONTRACT_KINDS)}")
    if record.conformance_status not in CONFORMANCE_STATUSES:
        raise AcesPackageSourceError(f"conformance_status must be one of {sorted(CONFORMANCE_STATUSES)}")
    _require_single_line_ref("contract_profile", record.contract_profile, required=True)
    _require_single_line_ref("package_ref", record.package_ref, required=True)
    _require_single_line_ref("package_version", record.package_version, required=True)
    _require_single_line_ref("lock_ref", record.lock_ref, required=False)
    _require_single_line_ref("conformance_report_ref", record.conformance_report_ref, required=False)
    _require_digest("package_digest", record.package_digest, required=True)
    _require_digest("lock_digest", record.lock_digest, required=False)
    return _validate_provenance(record.provenance)
