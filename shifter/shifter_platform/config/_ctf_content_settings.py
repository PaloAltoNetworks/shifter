"""Deployment-owned native CTF scenario-content settings."""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from shared.schemas.ctf_content_reference import (
    CtfContentReferenceCatalog,
    CtfContentReferenceError,
    load_ctf_content_references_json,
)

__all__ = [
    "CTF_CONTENT_BUCKET",
    "CTF_CONTENT_MAX_BYTES",
    "CTF_CONTENT_PREFIX",
    "CTF_CONTENT_REFERENCES",
]

_DEFAULT_MAX_BYTES = 8 * 1024 * 1024
_MAX_ALLOWED_BYTES = 8 * 1024 * 1024

CTF_CONTENT_BUCKET = os.environ.get("SHIFTER_CTF_CONTENT_BUCKET", "").strip()
CTF_CONTENT_PREFIX = os.environ.get("SHIFTER_CTF_CONTENT_PREFIX", "ctf/content-bundles").strip()


def _load_max_bytes() -> int:
    """Load and validate the deployment's content-object byte limit."""
    raw = os.environ.get("SHIFTER_CTF_CONTENT_MAX_BYTES", str(_DEFAULT_MAX_BYTES)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured("SHIFTER_CTF_CONTENT_MAX_BYTES must be an integer") from exc
    if not 1 <= value <= _MAX_ALLOWED_BYTES:
        raise ImproperlyConfigured(f"SHIFTER_CTF_CONTENT_MAX_BYTES must be between 1 and {_MAX_ALLOWED_BYTES}")
    return value


def _load_references() -> CtfContentReferenceCatalog:
    """Load the closed reference catalog and its required bucket binding."""
    try:
        catalog = load_ctf_content_references_json(
            os.environ.get("SHIFTER_CTF_CONTENT_REFERENCES_JSON", ""),
            prefix=CTF_CONTENT_PREFIX,
        )
    except CtfContentReferenceError as exc:
        raise ImproperlyConfigured(f"SHIFTER_CTF_CONTENT_REFERENCES_JSON is invalid: {exc}") from exc
    if catalog.references and not CTF_CONTENT_BUCKET:
        raise ImproperlyConfigured("SHIFTER_CTF_CONTENT_BUCKET is required when content references are configured")
    return catalog


CTF_CONTENT_MAX_BYTES = _load_max_bytes()
CTF_CONTENT_REFERENCES = _load_references()
