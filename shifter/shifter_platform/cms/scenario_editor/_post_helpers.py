"""Scenario editor form and YAML post helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cms.scenarios.registry import get_scenario_detail

from ._common import ScenarioEditorError
from ._validation import validate_scenario_id

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from cms.models import Scenario

FIELD_DESCRIPTION = "description"
FIELD_ID = "id"
FIELD_INSTANCES = "instances"
FIELD_INSTANCES_JSON = "instances_json"
FIELD_NAME = "name"
FIELD_NEW_NAME = "new_name"
FIELD_NEW_SCENARIO_ID = "new_scenario_id"
FIELD_NGFW = "ngfw"
FIELD_SCENARIO_ID = "scenario_id"
FIELD_SUBNETS = "subnets"
FIELD_SUBNETS_JSON = "subnets_json"


def _public_services() -> Any:
    """Return the public facade so callers can patch the stable import path."""
    from cms.scenario_editor import services

    return services


@dataclass(frozen=True)
class ScenarioFormFields:
    """Validated form-submitted scenario fields."""

    scenario_id: str
    name: str
    description: str
    ngfw: bool
    instances: object
    subnets: object

    @property
    def definition(self) -> dict[str, Any]:
        return {FIELD_INSTANCES: self.instances, FIELD_SUBNETS: self.subnets, FIELD_NGFW: self.ngfw}

    def as_context(self, *, include_id: bool) -> dict[str, Any]:
        context = {
            FIELD_NAME: self.name,
            FIELD_DESCRIPTION: self.description,
            FIELD_NGFW: self.ngfw,
            FIELD_INSTANCES: self.instances,
            FIELD_SUBNETS: self.subnets,
        }
        if include_id:
            context[FIELD_ID] = self.scenario_id
        return context


@dataclass(frozen=True)
class ScenarioYamlFields:
    """Validated YAML-submitted scenario fields."""

    scenario_id: str
    name: str
    description: str
    definition: dict[str, Any]


def _post_value(post_data: Mapping[str, Any], key: str, default: str = "") -> str:
    """Return a stripped scalar POST value for form parsing."""
    value = post_data.get(key, default)
    if isinstance(value, list):
        value = value[-1] if value else default
    if value is None:
        value = default
    return str(value).strip()


def _load_json_field(raw_value: str, label: str) -> tuple[object, list[str]]:
    """Parse a JSON form field and return validation errors."""
    try:
        return json.loads(raw_value), []
    except (json.JSONDecodeError, TypeError):
        return [], [f"Invalid {label} JSON"]


def parse_scenario_form_fields(
    post_data: Mapping[str, Any], *, require_id: bool
) -> tuple[ScenarioFormFields, list[str]]:
    """Validate scenario create/edit form fields."""
    scenario_id = _post_value(post_data, FIELD_SCENARIO_ID)
    name = _post_value(post_data, FIELD_NAME)
    description = _post_value(post_data, FIELD_DESCRIPTION)
    ngfw = _post_value(post_data, FIELD_NGFW) == "on"
    instances, instance_errors = _load_json_field(_post_value(post_data, FIELD_INSTANCES_JSON, "[]"), FIELD_INSTANCES)
    subnets, subnet_errors = _load_json_field(_post_value(post_data, FIELD_SUBNETS_JSON, "[]"), FIELD_SUBNETS)

    errors: list[str] = []
    if require_id:
        if not scenario_id:
            errors.append("Scenario ID is required")
        else:
            try:
                validate_scenario_id(scenario_id)
            except ScenarioEditorError:
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
        _public_services().create_scenario(
            user,
            scenario_id=fields.scenario_id,
            name=fields.name,
            description=fields.description,
            definition=fields.definition,
        )
    except ScenarioEditorError as e:
        return fields, [e.public_message]
    return fields, []


def update_scenario_from_form_post(
    user: User, scenario_id: str, post_data: Mapping[str, Any]
) -> tuple[ScenarioFormFields, list[str]]:
    """Update a scenario from submitted form fields."""
    fields, errors = parse_scenario_form_fields(post_data, require_id=False)
    if errors:
        return fields, errors

    try:
        _public_services().update_scenario(
            user,
            scenario_id,
            name=fields.name,
            description=fields.description,
            definition=fields.definition,
        )
    except ScenarioEditorError as e:
        return fields, [e.public_message]
    return fields, []


def _definition_from_yaml_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    """Extract the persisted scenario definition fields from parsed YAML."""
    return {
        FIELD_INSTANCES: parsed.get(FIELD_INSTANCES, []),
        FIELD_SUBNETS: parsed.get(FIELD_SUBNETS, []),
        FIELD_NGFW: parsed.get(FIELD_NGFW, False),
    }


def parse_yaml_create_fields(yaml_content: str) -> tuple[ScenarioYamlFields | None, list[str]]:
    """Validate YAML fields required to create a scenario."""
    parsed, errors = _public_services().validate_yaml(yaml_content)
    if errors:
        return None, errors

    parsed = parsed or {}
    scenario_id = str(parsed.get(FIELD_ID) or "").strip()
    name = str(parsed.get(FIELD_NAME) or "").strip()
    description = str(parsed.get(FIELD_DESCRIPTION) or "").strip()

    yaml_errors = []
    if not scenario_id:
        yaml_errors.append(f"YAML must include an '{FIELD_ID}' field")
    if not name:
        yaml_errors.append(f"YAML must include a '{FIELD_NAME}' field")
    if not description:
        yaml_errors.append(f"YAML must include a '{FIELD_DESCRIPTION}' field")
    if yaml_errors:
        return None, yaml_errors

    return ScenarioYamlFields(scenario_id, name, description, _definition_from_yaml_fields(parsed)), []


def create_scenario_from_yaml_post(user: User, yaml_content: str) -> tuple[ScenarioYamlFields | None, list[str]]:
    """Create a scenario from submitted YAML content."""
    fields, errors = parse_yaml_create_fields(yaml_content)
    if errors or fields is None:
        return fields, errors

    try:
        _public_services().create_scenario(
            user,
            scenario_id=fields.scenario_id,
            name=fields.name,
            description=fields.description,
            definition=fields.definition,
        )
    except ScenarioEditorError as e:
        return fields, [e.public_message]
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
    parsed, errors = _public_services().validate_yaml(yaml_content)
    if errors:
        return errors

    parsed = parsed or {}
    try:
        _public_services().update_scenario(
            user,
            scenario_id,
            name=parsed.get(FIELD_NAME, fallback_name),
            description=parsed.get(FIELD_DESCRIPTION, fallback_description),
            definition=_definition_from_yaml_fields(parsed),
        )
    except ScenarioEditorError as e:
        return [e.public_message]
    return []


def clone_scenario_from_form_post(
    user: User, source_scenario_id: str, post_data: Mapping[str, Any]
) -> tuple[Scenario | None, str | None, list[str]]:
    """Clone a scenario from submitted clone-form fields."""
    new_scenario_id = _post_value(post_data, FIELD_NEW_SCENARIO_ID)
    new_name = _post_value(post_data, FIELD_NEW_NAME) or None
    if not new_scenario_id:
        return None, new_name, ["New scenario ID is required"]

    try:
        scenario = _public_services().clone_scenario(
            user,
            source_scenario_id,
            new_scenario_id=new_scenario_id,
            new_name=new_name,
        )
    except ScenarioEditorError as e:
        return None, new_name, [e.public_message]
    return scenario, new_name, []


def toggle_scenario_metadata_flag(user: User, scenario_id: str, *, field: str, default: bool) -> bool:
    """Toggle a boolean scenario metadata flag and return the new value."""
    current = get_scenario_detail(scenario_id)
    new_value = not current.get(field, default)
    _public_services().update_metadata(user, scenario_id, **{field: new_value})
    return new_value
