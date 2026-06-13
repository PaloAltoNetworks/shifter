"""Scenario Editor service layer.

Business logic for creating, updating, deleting, and validating
scenario templates. Uses CMS models directly.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import yaml
from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from cms.models import Scenario, ScenarioMetadata
from cms.scenarios.registry import is_default_scenario
from cms.scenarios.schema import ScenarioTemplate
from risk_register.models import AuditLog
from risk_register.services import AuditEvent, audit_log
from shared.auth import validate_cms_authoring_user
from shared.exceptions import CMSError
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class ScenarioEditorError(CMSError):
    """Error raised by scenario editor operations."""


@dataclass(frozen=True)
class ScenarioFormFields:
    """Validated form-submitted scenario fields."""

    scenario_id: str
    name: str
    description: str
    ngfw: bool
    instances: Any
    subnets: Any

    @property
    def definition(self) -> dict[str, Any]:
        return {"instances": self.instances, "subnets": self.subnets, "ngfw": self.ngfw}

    def as_context(self, *, include_id: bool) -> dict[str, Any]:
        context = {
            "name": self.name,
            "description": self.description,
            "ngfw": self.ngfw,
            "instances": self.instances,
            "subnets": self.subnets,
        }
        if include_id:
            context["id"] = self.scenario_id
        return context


@dataclass(frozen=True)
class ScenarioYamlFields:
    """Validated YAML-submitted scenario fields."""

    scenario_id: str
    name: str
    description: str
    definition: dict[str, Any]


def _validate_user(user: User, func_name: str) -> None:
    """Delegate to the shared CMS authoring user validator (see shared.auth)."""
    validate_cms_authoring_user(user, func_name)


# Regex for valid scenario IDs: lowercase alphanumeric, hyphens, underscores.
# Must start and end with a letter or digit.
_SCENARIO_ID_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$")


def _post_value(post_data: Mapping[str, Any], key: str, default: str = "") -> str:
    value = post_data.get(key, default)
    if isinstance(value, list):
        value = value[-1] if value else default
    if value is None:
        value = default
    return str(value).strip()


def _load_json_field(raw_value: str, label: str) -> tuple[Any, list[str]]:
    try:
        return json.loads(raw_value), []
    except (json.JSONDecodeError, TypeError):
        return [], [f"Invalid {label} JSON"]


def parse_scenario_form_fields(
    post_data: Mapping[str, Any], *, require_id: bool
) -> tuple[ScenarioFormFields, list[str]]:
    """Validate scenario create/edit form fields."""
    scenario_id = _post_value(post_data, "scenario_id")
    name = _post_value(post_data, "name")
    description = _post_value(post_data, "description")
    ngfw = _post_value(post_data, "ngfw") == "on"
    instances, instance_errors = _load_json_field(_post_value(post_data, "instances_json", "[]"), "instances")
    subnets, subnet_errors = _load_json_field(_post_value(post_data, "subnets_json", "[]"), "subnets")

    errors: list[str] = []
    if require_id:
        if not scenario_id:
            errors.append("Scenario ID is required")
        elif not _SCENARIO_ID_RE.match(scenario_id):
            errors.append("Scenario ID must contain only lowercase letters, numbers, hyphens, and underscores")
    if not name:
        errors.append("Name is required")
    if not description:
        errors.append("Description is required")

    errors.extend(instance_errors)
    errors.extend(subnet_errors)
    if not instances:
        errors.append("At least one instance is required")

    return ScenarioFormFields(scenario_id, name, description, ngfw, instances, subnets), errors


def create_scenario_from_form_post(user: User, post_data: Mapping[str, Any]) -> tuple[ScenarioFormFields, list[str]]:
    """Create a scenario from submitted form fields."""
    fields, errors = parse_scenario_form_fields(post_data, require_id=True)
    if errors:
        return fields, errors

    try:
        create_scenario(
            user,
            scenario_id=fields.scenario_id,
            name=fields.name,
            description=fields.description,
            definition=fields.definition,
        )
    except ScenarioEditorError as e:
        return fields, [str(e)]
    return fields, []


def update_scenario_from_form_post(
    user: User, scenario_id: str, post_data: Mapping[str, Any]
) -> tuple[ScenarioFormFields, list[str]]:
    """Update a scenario from submitted form fields."""
    fields, errors = parse_scenario_form_fields(post_data, require_id=False)
    if errors:
        return fields, errors

    try:
        update_scenario(
            user,
            scenario_id,
            name=fields.name,
            description=fields.description,
            definition=fields.definition,
        )
    except ScenarioEditorError as e:
        return fields, [str(e)]
    return fields, []


def _definition_from_yaml_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "instances": parsed.get("instances", []),
        "subnets": parsed.get("subnets", []),
        "ngfw": parsed.get("ngfw", False),
    }


def parse_yaml_create_fields(yaml_content: str) -> tuple[ScenarioYamlFields | None, list[str]]:
    """Validate YAML fields required to create a scenario."""
    parsed, errors = validate_yaml(yaml_content)
    if errors:
        return None, errors

    parsed = parsed or {}
    scenario_id = str(parsed.get("id") or "").strip()
    name = str(parsed.get("name") or "").strip()
    description = str(parsed.get("description") or "").strip()

    yaml_errors = []
    if not scenario_id:
        yaml_errors.append("YAML must include an 'id' field")
    if not name:
        yaml_errors.append("YAML must include a 'name' field")
    if not description:
        yaml_errors.append("YAML must include a 'description' field")
    if yaml_errors:
        return None, yaml_errors

    return ScenarioYamlFields(scenario_id, name, description, _definition_from_yaml_fields(parsed)), []


def create_scenario_from_yaml_post(user: User, yaml_content: str) -> tuple[ScenarioYamlFields | None, list[str]]:
    """Create a scenario from submitted YAML content."""
    fields, errors = parse_yaml_create_fields(yaml_content)
    if errors or fields is None:
        return fields, errors

    try:
        create_scenario(
            user,
            scenario_id=fields.scenario_id,
            name=fields.name,
            description=fields.description,
            definition=fields.definition,
        )
    except ScenarioEditorError as e:
        return fields, [str(e)]
    return fields, []


def update_scenario_from_yaml_post(
    user: User,
    scenario_id: str,
    yaml_content: str,
    *,
    fallback_name: str,
    fallback_description: str,
) -> list[str]:
    """Update a scenario from submitted YAML content."""
    parsed, errors = validate_yaml(yaml_content)
    if errors:
        return errors

    parsed = parsed or {}
    try:
        update_scenario(
            user,
            scenario_id,
            name=parsed.get("name", fallback_name),
            description=parsed.get("description", fallback_description),
            definition=_definition_from_yaml_fields(parsed),
        )
    except ScenarioEditorError as e:
        return [str(e)]
    return []


def clone_scenario_from_form_post(
    user: User, source_scenario_id: str, post_data: Mapping[str, Any]
) -> tuple[Scenario | None, str | None, list[str]]:
    """Clone a scenario from submitted clone-form fields."""
    new_scenario_id = _post_value(post_data, "new_scenario_id")
    new_name = _post_value(post_data, "new_name") or None
    if not new_scenario_id:
        return None, new_name, ["New scenario ID is required"]

    try:
        scenario = clone_scenario(
            user,
            source_scenario_id,
            new_scenario_id=new_scenario_id,
            new_name=new_name,
        )
    except ScenarioEditorError as e:
        return None, new_name, [str(e)]
    return scenario, new_name, []


def toggle_scenario_metadata_flag(user: User, scenario_id: str, *, field: str, default: bool) -> bool:
    """Toggle a boolean scenario metadata flag and return the new value."""
    from cms.scenarios.registry import get_scenario_detail

    current = get_scenario_detail(scenario_id)
    new_value = not current.get(field, default)
    update_metadata(user, scenario_id, **{field: new_value})
    return new_value


def new_scenario_template_yaml() -> str:
    """Return the starter YAML shown by the YAML create view."""
    return (
        "id: my-new-scenario\n"
        "name: My New Scenario\n"
        "description: Describe your scenario here.\n"
        "ngfw: false\n"
        "\n"
        "instances:\n"
        "  - name: Attacker\n"
        "    role: attacker\n"
        "    os_type: kali\n"
        "    xdr_agent: false\n"
        "\n"
        "  - name: Workstation\n"
        "    role: victim\n"
        "    os_type: from_agent\n"
        "    xdr_agent: true\n"
        "\n"
        "subnets:\n"
        "  - name: core\n"
        "    instances: [Attacker, Workstation]\n"
    )


def validate_definition(definition: dict[str, Any]) -> list[str]:
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
        return None, ["Invalid YAML format"]

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
    definition: dict[str, Any],
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
        safe_log_value(scenario_id),
    )

    # Validate scenario_id format
    if not _SCENARIO_ID_RE.match(scenario_id):
        logger.error(
            "create_scenario: invalid scenario_id format: %s, user_id=%s",
            safe_log_value(scenario_id),
            user.id,
        )
        raise ScenarioEditorError(
            f"Invalid scenario ID '{scenario_id}': must be lowercase letters, numbers, hyphens, and underscores"
        )

    # Check collision with YAML defaults
    if is_default_scenario(scenario_id):
        logger.error(
            "create_scenario: conflicts with default scenario, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
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
            safe_log_value(scenario_id),
            user.id,
        )
        raise ScenarioEditorError(f"Invalid scenario definition: {'; '.join(errors)}")

    try:
        with transaction.atomic():
            if Scenario.objects.filter(scenario_id=scenario_id).exists():
                logger.error(
                    "create_scenario: duplicate scenario_id=%s, user_id=%s",
                    safe_log_value(scenario_id),
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
            safe_log_value(scenario_id),
            user.id,
        )
        raise ScenarioEditorError(f"A scenario with ID '{scenario_id}' already exists") from None
    except (TypeError, ValueError, ScenarioEditorError):
        raise
    except Exception:
        logger.exception(
            "Error in create_scenario for user_id=%s, scenario_id=%s",
            user.id,
            safe_log_value(scenario_id),
        )
        raise

    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.SCENARIO,
            # Scenario PK is UUID; use 0 and store scenario_id in state
            entity_id=0,
            action=AuditLog.Action.CREATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"scenario_id": scenario_id, "name": name},
        )
    )
    logger.info(
        "Scenario created: scenario_id=%s by user_id=%s",
        safe_log_value(scenario_id),
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
        safe_log_value(scenario_id),
    )

    if is_default_scenario(scenario_id):
        logger.error(
            "update_scenario: cannot edit default scenario, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
            user.id,
        )
        raise ScenarioEditorError(
            f"Cannot edit default scenario '{scenario_id}'. Default scenarios are managed in code."
        )

    try:
        scenario = Scenario.objects.get(scenario_id=scenario_id)
    except Scenario.DoesNotExist as e:
        logger.error(
            "update_scenario: scenario not found, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
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
            safe_log_value(scenario_id),
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
            safe_log_value(scenario_id),
        )
        raise

    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.SCENARIO,
            # Scenario PK is UUID; use 0 and store scenario_id in state
            entity_id=0,
            action=AuditLog.Action.UPDATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"scenario_id": scenario_id, "name": scenario.name},
        )
    )
    logger.info(
        "Scenario updated: scenario_id=%s by user_id=%s",
        safe_log_value(scenario_id),
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
        safe_log_value(scenario_id),
    )

    if is_default_scenario(scenario_id):
        logger.error(
            "delete_scenario: cannot delete default scenario, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
            user.id,
        )
        raise ScenarioEditorError(
            f"Cannot delete default scenario '{scenario_id}'. Default scenarios are managed in code."
        )

    try:
        scenario = Scenario.objects.get(scenario_id=scenario_id)
    except Scenario.DoesNotExist as e:
        logger.error(
            "delete_scenario: scenario not found, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
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
            safe_log_value(scenario_id),
        )
        raise

    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.SCENARIO,
            # Scenario PK is UUID; use 0 and store scenario_id in state
            entity_id=0,
            action=AuditLog.Action.DELETE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            previous_state={"scenario_id": scenario_id, "name": scenario.name},
        )
    )
    logger.info(
        "Scenario deleted: scenario_id=%s by user_id=%s",
        safe_log_value(scenario_id),
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
        safe_log_value(scenario_id),
    )

    # Verify the scenario exists
    from cms.scenarios.registry import get_scenario_detail

    try:
        get_scenario_detail(scenario_id)
    except ValueError as e:
        logger.error(
            "update_metadata: scenario not found, scenario_id=%s, user_id=%s",
            safe_log_value(scenario_id),
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
            safe_log_value(scenario_id),
        )
        raise

    audit_log(
        AuditEvent(
            entity_type=AuditLog.EntityType.SCENARIO,
            # ScenarioMetadata PK is auto-int but use 0 for consistency
            entity_id=0,
            action=AuditLog.Action.UPDATE,
            actor_type=AuditLog.ActorType.USER,
            actor_id=user.id,
            new_state={"scenario_id": scenario_id, "enabled": metadata.enabled, "staff_only": metadata.staff_only},
        )
    )
    logger.info(
        "Scenario metadata updated: scenario_id=%s, enabled=%s, staff_only=%s by user_id=%s",
        safe_log_value(scenario_id),
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
        safe_log_value(source_scenario_id),
        safe_log_value(new_scenario_id),
    )

    from cms.scenarios.registry import get_scenario_detail

    try:
        source = get_scenario_detail(source_scenario_id)
    except ValueError as e:
        logger.error(
            "clone_scenario: source not found, source_scenario_id=%s, user_id=%s",
            safe_log_value(source_scenario_id),
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
    logger.debug("export_scenario_yaml called for scenario_id=%s", safe_log_value(scenario_id))

    from cms.scenarios.registry import get_scenario_detail

    try:
        data = get_scenario_detail(scenario_id)
    except ValueError as e:
        logger.error(
            "export_scenario_yaml: scenario not found, scenario_id=%s",
            safe_log_value(scenario_id),
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
