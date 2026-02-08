"""Scenario Editor service layer.

Business logic for creating, updating, deleting, and validating
scenario templates. Uses CMS models directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import yaml
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from cms.models import Scenario, ScenarioMetadata
from cms.scenarios.registry import is_default_scenario
from cms.scenarios.schema import ScenarioTemplate

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class ScenarioEditorError(Exception):
    """Error raised by scenario editor operations."""


def validate_definition(definition: dict) -> list[str]:
    """Validate a scenario definition against ScenarioTemplate schema.

    Builds a full ScenarioTemplate from the definition dict and
    validates it. Returns a list of human-readable error messages.

    Args:
        definition: Dict containing instances, subnets, ngfw, etc.
            Must also include id, name, description for full validation.

    Returns:
        Empty list if valid, or list of error message strings.
    """
    errors = []

    if not isinstance(definition, dict):
        return ["Definition must be a JSON object"]

    # Check required top-level fields
    required = ["id", "name", "description", "instances"]
    for field in required:
        if field not in definition:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    try:
        ScenarioTemplate.model_validate(definition)
    except PydanticValidationError as e:
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            errors.append(f"{loc}: {error['msg']}")

    return errors


def validate_yaml(yaml_content: str) -> tuple[dict | None, list[str]]:
    """Parse and validate YAML scenario content.

    Args:
        yaml_content: Raw YAML string.

    Returns:
        Tuple of (parsed_dict_or_None, list_of_errors).
    """
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        return None, [f"Invalid YAML: {e}"]

    if not isinstance(data, dict):
        return None, ["YAML must define a mapping (object), not a scalar or list"]

    errors = validate_definition(data)
    return (data if not errors else None), errors


def create_scenario(
    user: User,
    *,
    scenario_id: str,
    name: str,
    description: str,
    definition: dict,
) -> Scenario:
    """Create a new custom scenario.

    Args:
        user: Staff user creating the scenario.
        scenario_id: URL-safe unique identifier.
        name: Display name.
        description: User-facing description.
        definition: Scenario structure (instances, subnets, ngfw).

    Returns:
        Created Scenario instance.

    Raises:
        ScenarioEditorError: If scenario_id conflicts or definition is invalid.
    """
    # Check collision with YAML defaults
    if is_default_scenario(scenario_id):
        raise ScenarioEditorError(
            f"Scenario ID '{scenario_id}' conflicts with a built-in default scenario"
        )

    # Check collision with existing DB scenarios
    if Scenario.objects.filter(
        scenario_id=scenario_id,
        deleted_at__isnull=True,
    ).exists():
        raise ScenarioEditorError(
            f"A scenario with ID '{scenario_id}' already exists"
        )

    # Build full definition for validation
    full_def = {
        "id": scenario_id,
        "name": name,
        "description": description,
        **definition,
    }
    errors = validate_definition(full_def)
    if errors:
        raise ScenarioEditorError(
            f"Invalid scenario definition: {'; '.join(errors)}"
        )

    scenario = Scenario(
        scenario_id=scenario_id,
        name=name,
        description=description,
        definition=definition,
        created_by=user,
        updated_by=user,
    )
    scenario.save()

    logger.info(
        "Scenario created: scenario_id=%s by user_id=%s",
        scenario_id,
        user.id,
    )
    return scenario


def update_scenario(
    user: User,
    scenario_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    definition: dict | None = None,
) -> Scenario:
    """Update an existing custom scenario.

    Default scenarios cannot be updated through the editor.

    Args:
        user: Staff user updating the scenario.
        scenario_id: ID of the scenario to update.
        name: New name (or None to keep existing).
        description: New description (or None to keep existing).
        definition: New definition (or None to keep existing).

    Returns:
        Updated Scenario instance.

    Raises:
        ScenarioEditorError: If scenario not found, is a default, or definition is invalid.
    """
    if is_default_scenario(scenario_id):
        raise ScenarioEditorError(
            f"Cannot edit default scenario '{scenario_id}'. "
            "Default scenarios are managed in code."
        )

    try:
        scenario = Scenario.objects.get(
            scenario_id=scenario_id,
            deleted_at__isnull=True,
        )
    except Scenario.DoesNotExist:
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found")

    if name is not None:
        scenario.name = name
    if description is not None:
        scenario.description = description
    if definition is not None:
        scenario.definition = definition

    # Validate the full definition
    full_def = {
        "id": scenario.scenario_id,
        "name": scenario.name,
        "description": scenario.description,
        **scenario.definition,
    }
    errors = validate_definition(full_def)
    if errors:
        raise ScenarioEditorError(
            f"Invalid scenario definition: {'; '.join(errors)}"
        )

    scenario.updated_by = user
    scenario.save()

    logger.info(
        "Scenario updated: scenario_id=%s by user_id=%s",
        scenario_id,
        user.id,
    )
    return scenario


def delete_scenario(user: User, scenario_id: str) -> None:
    """Soft-delete a custom scenario.

    Default scenarios cannot be deleted through the editor.

    Args:
        user: Staff user deleting the scenario.
        scenario_id: ID of the scenario to delete.

    Raises:
        ScenarioEditorError: If scenario not found or is a default.
    """
    if is_default_scenario(scenario_id):
        raise ScenarioEditorError(
            f"Cannot delete default scenario '{scenario_id}'. "
            "Default scenarios are managed in code."
        )

    try:
        scenario = Scenario.objects.get(
            scenario_id=scenario_id,
            deleted_at__isnull=True,
        )
    except Scenario.DoesNotExist:
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found")

    scenario.deleted_at = timezone.now()
    scenario.updated_by = user
    scenario.save(update_fields=["deleted_at", "updated_by", "updated_at"])

    # Clean up metadata if it exists
    ScenarioMetadata.objects.filter(scenario_id=scenario_id).delete()

    logger.info(
        "Scenario deleted: scenario_id=%s by user_id=%s",
        scenario_id,
        user.id,
    )


def update_metadata(
    user: User,
    scenario_id: str,
    *,
    enabled: bool | None = None,
    staff_only: bool | None = None,
) -> ScenarioMetadata:
    """Update metadata (enabled, staff_only) for any scenario.

    Works for both default and custom scenarios. Creates the metadata
    row if it doesn't exist.

    Args:
        user: Staff user updating metadata.
        scenario_id: ID of the scenario.
        enabled: New enabled state (or None to keep existing).
        staff_only: New staff_only state (or None to keep existing).

    Returns:
        Updated ScenarioMetadata instance.

    Raises:
        ScenarioEditorError: If scenario doesn't exist in either source.
    """
    # Verify the scenario exists
    from cms.scenarios.registry import get_scenario_detail

    try:
        get_scenario_detail(scenario_id)
    except ValueError:
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found")

    metadata, created = ScenarioMetadata.objects.get_or_create(
        scenario_id=scenario_id,
        defaults={
            "enabled": enabled if enabled is not None else True,
            "staff_only": staff_only if staff_only is not None else False,
            "updated_by": user,
        },
    )

    if not created:
        if enabled is not None:
            metadata.enabled = enabled
        if staff_only is not None:
            metadata.staff_only = staff_only
        metadata.updated_by = user
        metadata.save()

    logger.info(
        "Scenario metadata updated: scenario_id=%s, enabled=%s, staff_only=%s by user_id=%s",
        scenario_id,
        metadata.enabled,
        metadata.staff_only,
        user.id,
    )
    return metadata


def clone_scenario(
    user: User,
    source_scenario_id: str,
    *,
    new_scenario_id: str,
    new_name: str | None = None,
) -> Scenario:
    """Clone an existing scenario (default or custom) into a new custom scenario.

    Args:
        user: Staff user creating the clone.
        source_scenario_id: ID of the scenario to clone.
        new_scenario_id: URL-safe ID for the new scenario.
        new_name: Display name for the clone (defaults to "Copy of <original>").

    Returns:
        Newly created Scenario instance.

    Raises:
        ScenarioEditorError: If source not found or new_scenario_id conflicts.
    """
    from cms.scenarios.registry import get_scenario_detail

    try:
        source = get_scenario_detail(source_scenario_id)
    except ValueError:
        raise ScenarioEditorError(
            f"Source scenario '{source_scenario_id}' not found"
        )

    clone_name = new_name or f"Copy of {source['name']}"

    # Build definition from source (structural parts only)
    definition = {
        "instances": source.get("instances", []),
        "subnets": source.get("subnets", []),
        "ngfw": source.get("ngfw", False),
    }

    return create_scenario(
        user,
        scenario_id=new_scenario_id,
        name=clone_name,
        description=source.get("description", ""),
        definition=definition,
    )


def export_scenario_yaml(scenario_id: str) -> str:
    """Export a scenario as YAML.

    Args:
        scenario_id: ID of the scenario to export.

    Returns:
        YAML string representation of the scenario.

    Raises:
        ScenarioEditorError: If scenario not found.
    """
    from cms.scenarios.registry import get_scenario_detail

    try:
        data = get_scenario_detail(scenario_id)
    except ValueError:
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found")

    # Build a clean YAML-friendly dict (exclude metadata fields)
    export = {
        "id": data["id"],
        "name": data["name"],
        "description": data["description"],
        "enabled": data.get("enabled", True),
        "ngfw": data.get("ngfw", False),
        "instances": data.get("instances", []),
    }
    if data.get("subnets"):
        export["subnets"] = data["subnets"]

    return yaml.dump(export, default_flow_style=False, sort_keys=False)
