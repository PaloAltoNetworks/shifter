"""Cross-backend installation boundary for model-access policy (PLAT-202).

The semantic models live in ``shared.model_access``.  This independently
packaged installer consumes their generated JSON Schema and publishes the
validated catalog as a mounted artifact; only its fixed path and digest enter
the runtime environment.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from shared.model_access import ContractError, seal_catalog, validate_catalog

from .errors import ConfigIssue

SETTINGS_KEY = "model_access"
DEFAULT_CATALOG_PATH = "/etc/shifter/model-access/catalog.json"
_SCHEMA_PATH = Path(__file__).with_name("published_contract") / "model-access-policy.v1.schema.json"
_ENVELOPE_KEYS = frozenset({"enabled", "catalog"})


def compute_catalog_digest(catalog: Mapping[str, Any]) -> str:
    """Compute the v1 digest after canonical semantic validation and normalization."""
    semantic = dict(catalog)
    semantic.pop("digest", None)
    return seal_catalog(semantic).digest


def _schema() -> dict[str, Any]:
    """Operation for schema."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _issue_path(parts: list[object]) -> str:
    """Operation for issue path."""
    suffix = ".".join(str(item) for item in parts)
    return f"settings.{SETTINGS_KEY}.catalog" + (f".{suffix}" if suffix else "")


def validate_settings_block(settings: Mapping[str, Any]) -> tuple[dict[str, Any], list[ConfigIssue]]:
    """Validate and normalize ``settings.model_access`` without exposing values."""
    normalized = dict(settings)
    raw = settings.get(SETTINGS_KEY)
    issues: list[ConfigIssue] = []
    if raw is not None:
        model_access, issues = _normalize_model_access(raw)
        if not issues:
            normalized[SETTINGS_KEY] = model_access
    return normalized, issues


def _normalize_model_access(raw: object) -> tuple[dict[str, Any] | None, list[ConfigIssue]]:
    """Normalize one model-access envelope after bounded validation."""
    issue = _validate_envelope(raw)
    result: dict[str, Any] | None = None
    issues = [issue] if issue is not None else []
    if not issues:
        assert isinstance(raw, Mapping)
        enabled = raw.get("enabled", False)
        catalog = raw.get("catalog")
        if catalog is None:
            result = {"enabled": enabled, "catalog": None}
        else:
            assert isinstance(catalog, Mapping)
            issues = _validate_catalog_schema(catalog)
            if not issues:
                canonical, issue = _validate_catalog_semantics(catalog)
                if issue is not None:
                    issues.append(issue)
                else:
                    result = {"enabled": enabled, "catalog": canonical}
    return result, issues


def _validate_envelope(raw: object) -> ConfigIssue | None:
    """Operation for validate envelope."""
    issue = None
    if not isinstance(raw, Mapping):
        issue = ConfigIssue(f"settings.{SETTINGS_KEY}", "must be a mapping")
    else:
        unknown = sorted(set(raw) - _ENVELOPE_KEYS)
        enabled = raw.get("enabled", False)
        catalog = raw.get("catalog")
        if unknown:
            issue = ConfigIssue(f"settings.{SETTINGS_KEY}.{unknown[0]}", "unknown field")
        elif not isinstance(enabled, bool):
            issue = ConfigIssue(f"settings.{SETTINGS_KEY}.enabled", "must be a boolean")
        elif enabled and catalog is None:
            issue = ConfigIssue(f"settings.{SETTINGS_KEY}.catalog", "is required when enabled")
        elif catalog is not None and not isinstance(catalog, Mapping):
            issue = ConfigIssue(f"settings.{SETTINGS_KEY}.catalog", "must be a mapping")
    return issue


def _validate_catalog_schema(catalog: Mapping[str, Any]) -> list[ConfigIssue]:
    """Operation for validate catalog schema."""
    errors = sorted(Draft202012Validator(_schema()).iter_errors(catalog), key=lambda item: list(item.absolute_path))
    return [
        ConfigIssue(_issue_path(list(error.absolute_path)), "failed the model-access contract schema")
        for error in errors
    ]


def _validate_catalog_semantics(catalog: Mapping[str, Any]) -> tuple[dict[str, Any] | None, ConfigIssue | None]:
    """Operation for validate catalog semantics."""
    try:
        canonical = validate_catalog(catalog)
    except ContractError as exc:
        path = f"settings.{SETTINGS_KEY}.catalog"
        if exc.path != "<root>":
            path = f"{path}.{exc.path}"
        return None, ConfigIssue(path, f"failed semantic validation ({exc.code})")
    return canonical.model_dump(mode="json"), None
