"""Fail-closed runtime binding for the mounted model-access catalog."""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from shared.model_access import ContractError, ModelAccessCatalog
from shared.model_access.runtime import load_mounted_catalog


def load_model_access_catalog(*, enabled: bool, path: str, expected_digest: str) -> ModelAccessCatalog | None:
    """Reparse a bounded mounted artifact and bind it to the rendered digest."""
    try:
        return load_mounted_catalog(enabled=enabled, path=path, expected_digest=expected_digest)
    except ContractError as exc:
        messages = {
            "runtime.catalog_required": "enabled model access requires a catalog path and digest",
            "runtime.catalog_reference_incomplete": "model access catalog path and digest must be configured together",
            "runtime.catalog_too_large": "model access catalog exceeds the maximum size",
            "runtime.catalog_unreadable": "model access catalog could not be read",
            "runtime.catalog_digest_mismatch": "model access catalog does not match the expected digest",
            "runtime.catalog_disabled": "runtime model access cannot enable a catalog declared disabled",
        }
        raise ImproperlyConfigured(messages.get(exc.code, "model access catalog is invalid")) from exc


MODEL_ACCESS_ENABLED = os.environ.get("MODEL_ACCESS_ENABLED", "false").strip().lower() == "true"
MODEL_ACCESS_CATALOG_PATH = os.environ.get("MODEL_ACCESS_CATALOG_PATH", "").strip()
MODEL_ACCESS_CATALOG_DIGEST = os.environ.get("MODEL_ACCESS_CATALOG_DIGEST", "").strip()
MODEL_ACCESS_CATALOG = load_model_access_catalog(
    enabled=MODEL_ACCESS_ENABLED,
    path=MODEL_ACCESS_CATALOG_PATH,
    expected_digest=MODEL_ACCESS_CATALOG_DIGEST,
)

__all__ = [
    "MODEL_ACCESS_CATALOG",
    "MODEL_ACCESS_CATALOG_DIGEST",
    "MODEL_ACCESS_CATALOG_PATH",
    "MODEL_ACCESS_ENABLED",
]
