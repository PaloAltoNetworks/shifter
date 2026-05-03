"""Scenario Editor service layer.

Business logic for creating, updating, deleting, and validating
scenario templates. Uses CMS models directly.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import yaml
from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from cms.models import Scenario, ScenarioMetadata
from cms.scenarios.registry import is_default_scenario
from cms.scenarios.schema import ScenarioTemplate
from risk_register.models import AuditLog
from risk_register.services import audit_log
from shared.constants import USER_CANNOT_BE_NONE, USER_MUST_BE_SAVED
from shared.exceptions import CMSError

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class ScenarioEditorError(CMSError):
    """Error raised by scenario editor operations."""


def _validate_user(user: User, func_name: str) -> None:
    """Validate user parameter — matches cms/services.py pattern."""
    if user is None:
        logger.error("%s called with None user", func_name)
        raise TypeError(USER_CANNOT_BE_NONE)
    if not hasattr(user, "id"):
        logger.error(
            "%s called with invalid user type: %s",
            func_name,
            type(user).__name__,
        )
        raise TypeError(f"user must be a User instance, got {type(user).__name__}")
    if user.id is None:
        logger.error("%s called with unsaved user (id=None)", func_name)
        raise ValueError(USER_MUST_BE_SAVED)


# Regex for valid scenario IDs: lowercase alphanumeric, hyphens, underscores.
# Must start and end with a letter or digit.
_SCENARIO_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")


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
        logger.warning("validate_yaml: YAML parse error: %s", e)
        return None, [f"Invalid YAML: {e}"]

    if not isinstance(data, dict):
        logger.warning("validate_yaml: YAML is not a mapping")
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
        TypeError: If user is None or invalid type.
        ValueError: If user has no ID (unsaved).
    """
    _validate_user(user, "create_scenario")
    logger.debug(
        "create_scenario called for user_id=%s, scenario_id=%s",
        user.id,
        scenario_id,
    )

    # Validate scenario_id format
    if not _SCENARIO_ID_RE.match(scenario_id):
        logger.error(
            "create_scenario: invalid scenario_id format: %s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(
            f"Invalid scenario ID '{scenario_id}': must be lowercase letters, numbers, hyphens, and underscores"
        )

    # Check collision with YAML defaults
    if is_default_scenario(scenario_id):
        logger.error(
            "create_scenario: conflicts with default scenario, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"Scenario ID '{scenario_id}' conflicts with a built-in default scenario")

    # Build full definition for validation
    full_def = {
        "id": scenario_id,
        "name": name,
        "description": description,
        **definition,
    }
    errors = validate_definition(full_def)
    if errors:
        logger.error(
            "create_scenario: invalid definition, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"Invalid scenario definition: {'; '.join(errors)}")

    try:
        with transaction.atomic():
            if Scenario.objects.active().filter(scenario_id=scenario_id).exists():
                logger.error(
                    "create_scenario: duplicate scenario_id=%s, user_id=%s",
                    scenario_id,
                    user.id,
                )
                raise ScenarioEditorError(f"A scenario with ID '{scenario_id}' already exists")

            scenario = Scenario(
                scenario_id=scenario_id,
                name=name,
                description=description,
                definition=definition,
                created_by=user,
                updated_by=user,
            )
            try:
                scenario.save()
            except PydanticValidationError as e:
                raise ScenarioEditorError(f"Invalid scenario definition: {e}") from e
    except IntegrityError:
        logger.error(
            "create_scenario: integrity error (race), scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"A scenario with ID '{scenario_id}' already exists") from None
    except (TypeError, ValueError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in create_scenario for user_id=%s, scenario_id=%s",
            user.id,
            scenario_id,
        )
        raise

    audit_log(
        entity_type=AuditLog.EntityType.SCENARIO,
        entity_id=0,  # Scenario PK is UUID; use 0 and store scenario_id in state
        action=AuditLog.Action.CREATE,
        actor_type=AuditLog.ActorType.USER,
        actor_id=user.id,
        new_state={"scenario_id": scenario_id, "name": name},
    )
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
        TypeError: If user is None or invalid type.
        ValueError: If user has no ID (unsaved).
    """
    _validate_user(user, "update_scenario")
    logger.debug(
        "update_scenario called for user_id=%s, scenario_id=%s",
        user.id,
        scenario_id,
    )

    if is_default_scenario(scenario_id):
        logger.error(
            "update_scenario: cannot edit default scenario, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(
            f"Cannot edit default scenario '{scenario_id}'. Default scenarios are managed in code."
        )

    try:
        scenario = Scenario.objects.active().get(scenario_id=scenario_id)
    except Scenario.DoesNotExist as e:
        logger.error(
            "update_scenario: scenario not found, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found") from e

    update_fields = ["updated_by", "updated_at"]
    if name is not None:
        scenario.name = name
        update_fields.append("name")
    if description is not None:
        scenario.description = description
        update_fields.append("description")
    if definition is not None:
        scenario.definition = definition
        update_fields.append("definition")

    # Validate the full definition
    full_def = {
        "id": scenario.scenario_id,
        "name": scenario.name,
        "description": scenario.description,
        **scenario.definition,
    }
    errors = validate_definition(full_def)
    if errors:
        logger.error(
            "update_scenario: invalid definition, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"Invalid scenario definition: {'; '.join(errors)}")

    scenario.updated_by = user
    try:
        scenario.save(update_fields=update_fields)
    except PydanticValidationError as e:
        raise ScenarioEditorError(f"Invalid scenario definition: {e}") from e
    except (TypeError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in update_scenario for user_id=%s, scenario_id=%s",
            user.id,
            scenario_id,
        )
        raise

    audit_log(
        entity_type=AuditLog.EntityType.SCENARIO,
        entity_id=0,  # Scenario PK is UUID; use 0 and store scenario_id in state
        action=AuditLog.Action.UPDATE,
        actor_type=AuditLog.ActorType.USER,
        actor_id=user.id,
        new_state={"scenario_id": scenario_id, "name": scenario.name},
    )
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
        TypeError: If user is None or invalid type.
        ValueError: If user has no ID (unsaved).
    """
    _validate_user(user, "delete_scenario")
    logger.debug(
        "delete_scenario called for user_id=%s, scenario_id=%s",
        user.id,
        scenario_id,
    )

    if is_default_scenario(scenario_id):
        logger.error(
            "delete_scenario: cannot delete default scenario, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(
            f"Cannot delete default scenario '{scenario_id}'. Default scenarios are managed in code."
        )

    try:
        scenario = Scenario.objects.active().get(scenario_id=scenario_id)
    except Scenario.DoesNotExist as e:
        logger.error(
            "delete_scenario: scenario not found, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found") from e

    try:
        scenario.deleted_at = timezone.now()
        scenario.updated_by = user
        scenario.save(update_fields=["deleted_at", "updated_by", "updated_at"])

        # Clean up metadata if it exists
        ScenarioMetadata.objects.filter(scenario_id=scenario_id).delete()
    except (TypeError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in delete_scenario for user_id=%s, scenario_id=%s",
            user.id,
            scenario_id,
        )
        raise

    audit_log(
        entity_type=AuditLog.EntityType.SCENARIO,
        entity_id=0,  # Scenario PK is UUID; use 0 and store scenario_id in state
        action=AuditLog.Action.DELETE,
        actor_type=AuditLog.ActorType.USER,
        actor_id=user.id,
        previous_state={"scenario_id": scenario_id, "name": scenario.name},
    )
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
        TypeError: If user is None or invalid type.
        ValueError: If user has no ID (unsaved).
    """
    _validate_user(user, "update_metadata")
    logger.debug(
        "update_metadata called for user_id=%s, scenario_id=%s",
        user.id,
        scenario_id,
    )

    # Verify the scenario exists
    from cms.scenarios.registry import get_scenario_detail

    try:
        get_scenario_detail(scenario_id)
    except ValueError as e:
        logger.error(
            "update_metadata: scenario not found, scenario_id=%s, user_id=%s",
            scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found") from e

    try:
        metadata, created = ScenarioMetadata.objects.get_or_create(
            scenario_id=scenario_id,
            defaults={
                "enabled": enabled if enabled is not None else True,
                "staff_only": staff_only if staff_only is not None else False,
                "updated_by": user,
            },
        )

        if not created:
            update_fields = ["updated_by", "updated_at"]
            if enabled is not None:
                metadata.enabled = enabled
                update_fields.append("enabled")
            if staff_only is not None:
                metadata.staff_only = staff_only
                update_fields.append("staff_only")
            metadata.updated_by = user
            metadata.save(update_fields=update_fields)
    except (TypeError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in update_metadata for user_id=%s, scenario_id=%s",
            user.id,
            scenario_id,
        )
        raise

    audit_log(
        entity_type=AuditLog.EntityType.SCENARIO,
        entity_id=0,  # ScenarioMetadata PK is auto-int but use 0 for consistency
        action=AuditLog.Action.UPDATE,
        actor_type=AuditLog.ActorType.USER,
        actor_id=user.id,
        new_state={"scenario_id": scenario_id, "enabled": metadata.enabled, "staff_only": metadata.staff_only},
    )
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
        TypeError: If user is None or invalid type.
        ValueError: If user has no ID (unsaved).
    """
    _validate_user(user, "clone_scenario")
    logger.debug(
        "clone_scenario called for user_id=%s, source=%s, new_id=%s",
        user.id,
        source_scenario_id,
        new_scenario_id,
    )

    from cms.scenarios.registry import get_scenario_detail

    try:
        source = get_scenario_detail(source_scenario_id)
    except ValueError as e:
        logger.error(
            "clone_scenario: source not found, source_scenario_id=%s, user_id=%s",
            source_scenario_id,
            user.id,
        )
        raise ScenarioEditorError(f"Source scenario '{source_scenario_id}' not found") from e

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
    logger.debug("export_scenario_yaml called for scenario_id=%s", scenario_id)

    from cms.scenarios.registry import get_scenario_detail

    try:
        data = get_scenario_detail(scenario_id)
    except ValueError as e:
        logger.error(
            "export_scenario_yaml: scenario not found, scenario_id=%s",
            scenario_id,
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found") from e

    # Build a clean YAML-friendly dict (exclude metadata fields)
    export = {
        "id": data["id"],
        "name": data["name"],
        "description": data["description"],
        "ngfw": data.get("ngfw", False),
        "instances": data.get("instances", []),
    }
    if data.get("subnets"):
        export["subnets"] = data["subnets"]

    return yaml.dump(export, default_flow_style=False, sort_keys=False)
