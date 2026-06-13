"""Scenario-editor validation and YAML parsing."""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from cms.scenarios.schema import ScenarioTemplate

from ._common import ScenarioEditorError

logger = logging.getLogger(__name__)

# Regex for valid scenario IDs: lowercase alphanumeric, hyphens, underscores.
# Must start and end with a letter or digit.
_SCENARIO_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")


def validate_scenario_id(scenario_id: str) -> None:
    """Validate an editor-created scenario identifier."""
    if not _SCENARIO_ID_RE.match(scenario_id):
        raise ScenarioEditorError(
            f"Invalid scenario ID '{scenario_id}': must be lowercase letters, numbers, hyphens, and underscores"
        )


def build_full_definition(
    *,
    scenario_id: str,
    name: str,
    description: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Return the full schema payload while keeping persisted definition structural."""
    return {
        "id": scenario_id,
        "name": name,
        "description": description,
        **definition,
    }


def validate_definition(definition: dict[str, Any]) -> list[str]:
    """Validate a scenario definition against ScenarioTemplate schema."""
    errors = []

    if not isinstance(definition, dict):
        return ["Definition must be a JSON object"]

    required = ["id", "name", "description", "instances"]
    for field in required:
        if field not in definition:
            errors.append(f"Missing required field: {field}")

    if errors:
        logger.warning("validate_definition: missing required fields: %s", errors)
        return errors

    try:
        ScenarioTemplate.model_validate(definition)
    except PydanticValidationError as e:
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            errors.append(f"{loc}: {error['msg']}")
        logger.warning("validate_definition: schema validation failed: %s", errors)

    return errors


def validate_scenario_payload(
    *,
    scenario_id: str,
    name: str,
    description: str,
    definition: dict[str, Any],
) -> list[str]:
    """Validate a persisted structural definition plus scenario metadata."""
    full_definition = build_full_definition(
        scenario_id=scenario_id,
        name=name,
        description=description,
        definition=definition,
    )
    return validate_definition(full_definition)


def validate_yaml(yaml_content: str) -> tuple[dict | None, list[str]]:
    """Parse and validate YAML scenario content."""
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        logger.warning("validate_yaml: YAML parse error: %s", e)
        return None, [f"Invalid YAML: {e}"]

    if not isinstance(data, dict):
        logger.warning("validate_yaml: YAML is not a mapping")
        return None, ["YAML must define a mapping (object), not a scalar or list"]

    errors = validate_definition(data)
    return (data if not errors else None), errors
