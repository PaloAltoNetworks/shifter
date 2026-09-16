"""Bounded mounted-catalog loading shared by broker and application runtimes."""

from __future__ import annotations

import hmac
from pathlib import Path

from shared.model_access.catalog import ContractError, load_catalog_json
from shared.model_access.models import ModelAccessCatalog

MAX_MODEL_ACCESS_CATALOG_BYTES = 2 * 1024 * 1024


def load_mounted_catalog(*, enabled: bool, path: str, expected_digest: str) -> ModelAccessCatalog | None:
    """Reparse and bind an artifact without importing Django or hydrating secrets."""
    if not path and not expected_digest:
        if enabled:
            raise ContractError("runtime.catalog_required")
        return None
    if not path or not expected_digest:
        raise ContractError("runtime.catalog_reference_incomplete")
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_MODEL_ACCESS_CATALOG_BYTES + 1)
        if len(raw) > MAX_MODEL_ACCESS_CATALOG_BYTES:
            raise ContractError("runtime.catalog_too_large")
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError("runtime.catalog_unreadable") from exc
    catalog = load_catalog_json(text)
    if not hmac.compare_digest(catalog.digest, expected_digest):
        raise ContractError("runtime.catalog_digest_mismatch")
    if enabled and not catalog.enabled:
        raise ContractError("runtime.catalog_disabled")
    return catalog
