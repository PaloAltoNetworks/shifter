"""Strict deployment references for native CTF scenario content.

The reference catalog is deployment configuration, not scenario content.  It
maps an existing scenario id to one contained, digest-pinned object while the
bucket, prefix, size limit, provider, and credentials remain server-owned.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

REFERENCE_CONTRACT = "shifter-ctf-content-references/v1"
_MAX_CONFIG_BYTES = 65_536
_MAX_REFERENCES = 256
_MAX_KEY_LENGTH = 512
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class CtfContentReferenceError(ValueError):
    """Raised when deployment-owned CTF content references are malformed."""


@dataclass(frozen=True)
class CtfContentReference:
    """One immutable scenario-to-object reference."""

    scenario_id: str
    object_key: str
    digest: str


@dataclass(frozen=True)
class CtfContentReferenceCatalog:
    """Validated deployment reference catalog."""

    contract: str = REFERENCE_CONTRACT
    references: dict[str, CtfContentReference] = field(default_factory=dict)

    def get(self, scenario_id: str) -> CtfContentReference | None:
        """Return the configured reference for ``scenario_id``, if any."""
        return self.references.get(scenario_id)


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting duplicate keys."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CtfContentReferenceError("reference configuration contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_unknown_keys(value: Mapping[str, object], allowed: set[str], what: str) -> None:
    """Reject fields outside the closed set allowed for an object."""
    unknown = set(value) - allowed
    if unknown:
        raise CtfContentReferenceError(f"{what} contains unknown fields")


def _normalize_prefix(prefix: str) -> str:
    """Return a normalized contained object prefix."""
    normalized = prefix.strip().strip("/")
    if not normalized:
        raise CtfContentReferenceError("content object prefix must not be empty")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise CtfContentReferenceError("content object prefix must be a contained object path")
    return f"{path.as_posix()}/"


def _parse_scenario_id(value: object) -> str:
    """Return a valid scenario identifier."""
    scenario_id = value
    if not isinstance(scenario_id, str) or not _IDENTIFIER_RE.fullmatch(scenario_id):
        raise CtfContentReferenceError("content reference scenario_id is invalid")
    return scenario_id


def _parse_object_key(value: object, *, prefix: str) -> str:
    """Return a normalized object key contained by the configured prefix."""
    object_key = value
    if not isinstance(object_key, str) or not object_key or len(object_key) > _MAX_KEY_LENGTH:
        raise CtfContentReferenceError("content reference object_key is invalid")
    path = PurePosixPath(object_key)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or object_key != path.as_posix():
        raise CtfContentReferenceError("content reference object_key must be a normalized contained path")
    if not object_key.startswith(prefix):
        raise CtfContentReferenceError("content reference object_key is outside the configured prefix")
    return object_key


def _parse_digest(value: object) -> str:
    """Return a canonical lowercase SHA-256 digest."""
    digest = value
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise CtfContentReferenceError("content reference digest must be a lowercase sha256 digest")
    return digest


def _parse_reference(value: object, *, prefix: str) -> CtfContentReference:
    """Parse one immutable scenario-to-object reference."""
    if not isinstance(value, Mapping):
        raise CtfContentReferenceError("each content reference must be an object")
    _reject_unknown_keys(value, {"scenario_id", "object_key", "digest"}, "content reference")
    scenario_id = _parse_scenario_id(value.get("scenario_id"))
    object_key = _parse_object_key(value.get("object_key"), prefix=prefix)
    digest = _parse_digest(value.get("digest"))
    return CtfContentReference(scenario_id=scenario_id, object_key=object_key, digest=digest)


def load_ctf_content_references_json(raw: str, *, prefix: str) -> CtfContentReferenceCatalog:
    """Parse the closed reference catalog from deployment JSON."""
    text = (raw or "").strip()
    normalized_prefix = _normalize_prefix(prefix)
    if not text:
        return CtfContentReferenceCatalog()
    if len(text.encode("utf-8")) > _MAX_CONFIG_BYTES:
        raise CtfContentReferenceError("reference configuration exceeds its byte limit")
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except CtfContentReferenceError:
        raise
    except (TypeError, ValueError) as exc:
        raise CtfContentReferenceError("reference configuration is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise CtfContentReferenceError("reference configuration must be an object")
    _reject_unknown_keys(payload, {"contract", "references"}, "reference configuration")
    if payload.get("contract") != REFERENCE_CONTRACT:
        raise CtfContentReferenceError("reference configuration contract is unsupported")
    raw_references = payload.get("references")
    if not isinstance(raw_references, list):
        raise CtfContentReferenceError("reference configuration references must be a list")
    if len(raw_references) > _MAX_REFERENCES:
        raise CtfContentReferenceError("reference configuration has too many entries")

    references: dict[str, CtfContentReference] = {}
    for value in raw_references:
        reference = _parse_reference(value, prefix=normalized_prefix)
        if reference.scenario_id in references:
            raise CtfContentReferenceError("reference configuration contains a duplicate scenario_id")
        references[reference.scenario_id] = reference
    return CtfContentReferenceCatalog(references=references)


__all__ = [
    "REFERENCE_CONTRACT",
    "CtfContentReference",
    "CtfContentReferenceCatalog",
    "CtfContentReferenceError",
    "load_ctf_content_references_json",
]
