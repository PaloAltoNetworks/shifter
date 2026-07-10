"""Pure dict helpers for persisted spec envelopes (no Pydantic dependency).

Lives at the cyberscript package root so the ECS provisioner can import it
without loading the full Pydantic schema graph.
"""

from __future__ import annotations

from typing import Any

SPEC_SCHEMA_KEY = "spec_schema"
SPEC_VERSION_KEY = "spec_version"
PAYLOAD_KEY = "payload"
SPEC_VERSION = "1"


def is_wrapped_persisted_spec(blob: dict[str, Any] | None) -> bool:
    return bool(blob and SPEC_SCHEMA_KEY in blob and PAYLOAD_KEY in blob)


def unwrap_persisted_spec(blob: dict[str, Any] | None) -> dict[str, Any]:
    """Return the inner payload dict, passing legacy undiscriminated blobs through."""
    if not blob:
        return {}
    if is_wrapped_persisted_spec(blob):
        payload = blob[PAYLOAD_KEY]
        if isinstance(payload, dict):
            return payload
        msg = f"Expected dict payload for persisted spec, got {type(payload).__name__}"
        raise TypeError(msg)
    return blob


def ensure_wrapped_persisted_spec(slug: str, blob: dict[str, Any] | None) -> dict[str, Any]:
    """Return ``blob`` wrapped when it is legacy undiscriminated payload."""
    if not blob:
        return {}
    if is_wrapped_persisted_spec(blob):
        return blob
    return {
        SPEC_SCHEMA_KEY: slug,
        SPEC_VERSION_KEY: SPEC_VERSION,
        PAYLOAD_KEY: blob,
    }
