"""Bounded adapters for the canonical RAES environment-pack contract (#1578).

``raes-env-packs`` owns pack validation and canonical content identity.
This module keeps the CMS boundary small: it converts upstream validation
results into the existing ingestion exception, exposes the validated pack
identity, and gives registration/launch one shared digest-verification seam.
"""

from __future__ import annotations

from pathlib import Path

from raes_env_packs import (
    PackDigestError,
    pack_content_digest,
    verify_pack_content_digest,
)
from raes_env_packs import (
    validate_pack as validate_scenario_pack,
)

_ERROR_SUMMARY_CAP = 2048


class PackValidationError(ValueError):
    """Raised when an incoming pack fails the upstream consumer contract."""


def check_pack(pack_root: Path) -> list[str]:
    """Return upstream's stable, bounded diagnostics (``[]`` means valid)."""
    return validate_scenario_pack(pack_root).errors


def validate_pack(pack_root: Path) -> str:
    """Validate a foreign pack and return its contract-bound identity.

    The upstream consumer validator requires ``pack.yaml.name`` to equal the
    root directory name. Callers pass an already containment-checked path, so a
    successful validation makes that resolved basename the trusted identity.
    """
    errors = check_pack(pack_root)
    if errors:
        summary = "; ".join(errors)[:_ERROR_SUMMARY_CAP]
        raise PackValidationError(summary)
    return pack_root.resolve().name


def pack_digest(pack_root: Path) -> str:
    """Return the canonical, byte-bound RAES digest for ``pack_root``.

    Raises:
        PackDigestError: when the associated-artifact manifest, inventory, RAES
            parent, or payload bytes do not form one valid canonical identity.
    """
    return pack_content_digest(pack_root)


def verify_pack_digest(pack_root: Path, expected_digest: str) -> bool:
    """Verify current pack bytes against one canonical advertised digest."""
    return verify_pack_content_digest(pack_root, expected_digest)


__all__ = [
    "PackDigestError",
    "PackValidationError",
    "check_pack",
    "pack_digest",
    "validate_pack",
    "verify_pack_digest",
]
