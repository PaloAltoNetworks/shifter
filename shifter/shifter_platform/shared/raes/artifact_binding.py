"""Generation-fenced artifact-satisfaction binding transport (#1580, ADR-034-R8).

When the Engine resolves an authored artifact requirement at launch, it fences
the decision -- the upstream satisfaction disclosure plus the concrete backend
image it selected -- into the immutable ``OperationInput`` so the provisioner
realizes exactly that binding without re-resolving, querying the mutable
registry, choosing a different candidate, or falling back (ADR-034-R8).

This is a **plain-data**, byte-free carrier: it holds the portable disclosure
identity (requirement id + ``ArtifactIdentity`` fields + mechanism/acquisition/
timing) for audit and verification and the concrete provider ``image_ref`` (+
optional sizing) the provisioner applies. It carries no credential, URL, bucket,
signed URL, payload bytes, or secret. It is stdlib-only on purpose: the
standalone provisioner image imports it without RAES, Django, or pydantic
(ADR-031-R1 -- the provisioner consumes plain data, never the raes contracts).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["MAX_ARTIFACT_BINDINGS", "ArtifactBinding", "ArtifactBindingError"]

# Bounded well within MAX_ENVELOPE_BYTES: one binding per node with an artifact
# requirement, never a registry dump.
MAX_ARTIFACT_BINDINGS = 256

_SHA256_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_ACQUISITIONS = frozenset({"pull", "copy", "import", "local-lookup", "none"})
_TIMINGS = frozenset({"publication", "pack-ingestion", "backend-preparation", "realization"})

_KEYS = frozenset(
    {
        "target",
        "requirement_id",
        "artifact_id",
        "version",
        "digest",
        "media_type",
        "mechanism",
        "acquisition",
        "timing",
        "image_ref",
        "image_id",
        "machine_type",
        "disk_size_gb",
        "disk_type",
    }
)


class ArtifactBindingError(Exception):
    """The fenced artifact binding is not a valid, bounded, byte-free row."""


@dataclass(frozen=True)
class ArtifactBinding:
    """One node's fenced artifact-satisfaction decision.

    ``target`` is the compiled provisioning node address the binding realizes;
    ``image_ref`` is the concrete backend image the provisioner applies. The
    remaining fields echo the upstream satisfaction disclosure for audit and
    fail-closed verification. Sizing is optional (blank/``None`` lets the backend
    apply its default).
    """

    target: str
    requirement_id: str
    artifact_id: str
    version: str
    digest: str
    media_type: str
    mechanism: str
    acquisition: str
    timing: str
    image_ref: str
    machine_type: str = ""
    disk_size_gb: int | None = None
    disk_type: str = ""
    image_id: str = ""

    @classmethod
    def from_transport(cls, raw: Mapping[str, Any]) -> ArtifactBinding:
        """Rebuild a binding from transport, rejecting unknown keys and bad shapes."""
        if not isinstance(raw, Mapping):
            raise ArtifactBindingError("artifact binding must be an object")
        actual = frozenset(raw)
        unexpected = sorted(actual - _KEYS)
        if unexpected:
            raise ArtifactBindingError(f"artifact binding has unexpected field(s): {', '.join(unexpected)}")
        required = _KEYS - {"machine_type", "disk_size_gb", "disk_type", "image_id"}
        missing = sorted(required - actual)
        if missing:
            raise ArtifactBindingError(f"artifact binding is missing field(s): {', '.join(missing)}")

        digest = _require_str(raw, "digest")
        if not _SHA256_DIGEST.fullmatch(digest):
            raise ArtifactBindingError("artifact binding digest must be a canonical 'sha256:<64 hex>' value")
        acquisition = _require_str(raw, "acquisition")
        if acquisition not in _ACQUISITIONS:
            raise ArtifactBindingError(f"artifact binding acquisition must be one of {sorted(_ACQUISITIONS)}")
        timing = _require_str(raw, "timing")
        if timing not in _TIMINGS:
            raise ArtifactBindingError(f"artifact binding timing must be one of {sorted(_TIMINGS)}")

        return cls(
            target=_require_str(raw, "target"),
            requirement_id=_require_str(raw, "requirement_id"),
            artifact_id=_require_str(raw, "artifact_id"),
            version=_require_str(raw, "version"),
            digest=digest,
            media_type=_require_str(raw, "media_type"),
            mechanism=_require_str(raw, "mechanism"),
            acquisition=acquisition,
            timing=timing,
            image_ref=_require_str(raw, "image_ref"),
            image_id=_provider_image_id(raw.get("image_id", "")),
            machine_type=_optional_str(raw.get("machine_type")),
            disk_size_gb=_optional_positive_int(raw.get("disk_size_gb")),
            disk_type=_optional_str(raw.get("disk_type")),
        )

    def to_transport(self) -> dict[str, Any]:
        """Return the JSON-serialisable, byte-free transport row."""
        return {
            "target": self.target,
            "requirement_id": self.requirement_id,
            "artifact_id": self.artifact_id,
            "version": self.version,
            "digest": self.digest,
            "media_type": self.media_type,
            "mechanism": self.mechanism,
            "acquisition": self.acquisition,
            "timing": self.timing,
            "image_ref": self.image_ref,
            "image_id": self.image_id,
            "machine_type": self.machine_type,
            "disk_size_gb": self.disk_size_gb,
            "disk_type": self.disk_type,
        }


def _provider_image_id(value: object) -> str:
    """Legacy inventory has no provider ID; a supplied immutable ID must be valid."""
    if value == "":
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"[1-9]\d{0,19}", value):
        raise ArtifactBindingError("artifact image_id must be an immutable GCE numeric identity")
    return value


def _require_str(raw: Mapping[str, Any], field: str) -> str:
    """Return a non-empty string field, else fail closed."""
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ArtifactBindingError(f"artifact binding {field} must be a non-empty string")
    return value


def _optional_str(value: object) -> str:
    """Return a stripped string, or '' for absent/blank/non-string values."""
    return value if isinstance(value, str) and value.strip() else ""


def _optional_positive_int(value: object) -> int | None:
    """Return a positive int, or None; reject other shapes fail-closed."""
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ArtifactBindingError("artifact binding disk_size_gb must be a positive int or null")
    return value
