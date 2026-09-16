"""Strict entry points for the canonical model-access deployment catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from shared.model_access.digest import compute_digest, digest_matches
from shared.model_access.models import ModelAccessCatalog
from shared.model_access.sharing_models import SharingBinding

_ROOT_PATH = "<root>"
_VALIDATION_ERROR = "contract.validation"


class ContractError(ValueError):
    """Bounded contract failure safe for configuration and API error surfaces."""

    def __init__(self, code: str, path: str = _ROOT_PATH) -> None:
        """Operation for init."""
        self.code = code
        self.path = path
        super().__init__(f"{code} at {path}")


def _no_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Operation for no duplicate members."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("contract.duplicate_member", key)
        result[key] = value
    return result


def validate_catalog(payload: Mapping[str, Any]) -> ModelAccessCatalog:
    """Validate a mapping whose decoder already rejected duplicate members."""
    try:
        catalog = ModelAccessCatalog.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
        path = ".".join(str(part) for part in first.get("loc", ())) or _ROOT_PATH
        raise ContractError(_VALIDATION_ERROR, path) from exc
    for index, binding in enumerate(catalog.sharing_bindings):
        if not digest_matches(binding, binding.definition_digest):
            raise ContractError("contract.digest_mismatch", f"sharing_bindings.{index}.definition_digest")
    if not digest_matches(catalog, catalog.digest):
        raise ContractError("contract.digest_mismatch", "digest")
    return catalog


def seal_catalog(payload: Mapping[str, Any]) -> ModelAccessCatalog:
    """Validate, normalize, and attach the canonical digest to a new catalog."""
    candidate = dict(payload)
    candidate["digest"] = "sha256:" + "0" * 64
    try:
        catalog = ModelAccessCatalog.model_validate(candidate)
    except ValidationError as exc:
        first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
        path = ".".join(str(part) for part in first.get("loc", ())) or _ROOT_PATH
        raise ContractError(_VALIDATION_ERROR, path) from exc
    normalized = catalog.model_dump(mode="json")
    normalized["digest"] = compute_digest(catalog)
    return validate_catalog(normalized)


def seal_sharing_binding(payload: Mapping[str, Any]) -> SharingBinding:
    """Validate, normalize, and digest one binding before catalog publication."""
    candidate = dict(payload)
    candidate["definition_digest"] = "sha256:" + "0" * 64
    try:
        binding = SharingBinding.model_validate(candidate)
    except ValidationError as exc:
        first = exc.errors(include_url=False, include_context=False, include_input=False)[0]
        path = ".".join(str(part) for part in first.get("loc", ())) or _ROOT_PATH
        raise ContractError(_VALIDATION_ERROR, path) from exc
    normalized = binding.model_dump(mode="json")
    normalized["definition_digest"] = compute_digest(binding)
    return SharingBinding.model_validate(normalized)


def load_catalog_json(raw: str) -> ModelAccessCatalog:
    """Operation for load catalog json."""
    try:
        payload = json.loads(raw, object_pairs_hook=_no_duplicate_members, parse_constant=lambda _: _raise_non_finite())
    except ContractError:
        raise
    except (TypeError, ValueError) as exc:
        raise ContractError("contract.invalid_json") from exc
    if not isinstance(payload, Mapping):
        raise ContractError(_VALIDATION_ERROR)
    return validate_catalog(payload)


def _raise_non_finite() -> None:
    """Operation for raise non finite."""
    raise ContractError("contract.non_finite_number")


def model_access_catalog_schema() -> dict[str, Any]:
    """Return the generated installation schema's canonical source."""
    return ModelAccessCatalog.model_json_schema(mode="validation")
