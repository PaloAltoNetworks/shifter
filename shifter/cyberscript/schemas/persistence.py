"""Wrap and unwrap persisted spec JSON with schema/version discriminators."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from cyberscript.persisted_envelope import (
    PAYLOAD_KEY,
    SPEC_SCHEMA_KEY,
    SPEC_VERSION,
    SPEC_VERSION_KEY,
    ensure_wrapped_persisted_spec,
    is_wrapped_persisted_spec,
    unwrap_persisted_spec,
)
from .registry import get_model_for_slug


def wrap_persisted_spec(slug: str, model: BaseModel, *, mode: str = "json") -> dict[str, Any]:
    """Serialize a Pydantic model with schema/version metadata for DB storage."""
    if not isinstance(model, BaseModel):
        msg = f"wrap_persisted_spec expects a Pydantic model, got {type(model).__name__}"
        raise TypeError(msg)
    get_model_for_slug(slug)
    return {
        SPEC_SCHEMA_KEY: slug,
        SPEC_VERSION_KEY: SPEC_VERSION,
        PAYLOAD_KEY: model.model_dump(mode=mode),
    }


def validate_persisted_spec(blob: dict[str, Any], slug: str) -> BaseModel:
    """Validate a persisted blob (new or legacy format) against the expected schema."""
    if blob.get(SPEC_SCHEMA_KEY) and blob[SPEC_SCHEMA_KEY] != slug:
        msg = f"spec_schema mismatch: expected {slug}, got {blob[SPEC_SCHEMA_KEY]}"
        raise ValueError(msg)
    if blob.get(SPEC_VERSION_KEY) and blob[SPEC_VERSION_KEY] != SPEC_VERSION:
        msg = f"Unsupported spec_version: {blob[SPEC_VERSION_KEY]}"
        raise ValueError(msg)
    model_cls = get_model_for_slug(slug)
    payload = unwrap_persisted_spec(blob)
    return model_cls.model_validate(payload)


__all__ = [
    "PAYLOAD_KEY",
    "SPEC_SCHEMA_KEY",
    "SPEC_VERSION",
    "SPEC_VERSION_KEY",
    "ensure_wrapped_persisted_spec",
    "is_wrapped_persisted_spec",
    "unwrap_persisted_spec",
    "validate_persisted_spec",
    "wrap_persisted_spec",
]
