"""Wrap and unwrap persisted spec JSON with schema/version discriminators."""

from cyberscript.schemas.persistence import (
    PAYLOAD_KEY,
    SPEC_SCHEMA_KEY,
    SPEC_VERSION,
    SPEC_VERSION_KEY,
    ensure_wrapped_persisted_spec,
    is_wrapped_persisted_spec,
    unwrap_persisted_spec,
    validate_persisted_spec,
    wrap_persisted_spec,
)

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
