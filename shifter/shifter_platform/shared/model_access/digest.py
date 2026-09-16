"""Canonical JSON and digest functions for model-access v1 contracts."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from pydantic import BaseModel


def _semantic_data(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    """Operation for semantic data."""
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    data.pop("digest", None)
    data.pop("definition_digest", None)
    return data


def canonical_bytes(value: BaseModel | Mapping[str, Any]) -> bytes:
    """Encode normalized semantic data using the model-access v1 JSON profile."""
    return json.dumps(
        _semantic_data(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_digest(value: BaseModel | Mapping[str, Any]) -> str:
    """Operation for compute digest."""
    return "sha256:" + sha256(canonical_bytes(value)).hexdigest()


def digest_matches(value: BaseModel | Mapping[str, Any], claimed: str) -> bool:
    """Operation for digest matches."""
    return hmac.compare_digest(compute_digest(value), claimed)
