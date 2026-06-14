"""Public Scenario Editor service API.

Implementation lives in responsibility-focused package modules. This facade
preserves the import path used by views and existing callers.
"""

from __future__ import annotations

from ._common import ScenarioEditorError
from ._crud import clone_scenario, create_scenario, delete_scenario, update_scenario
from ._metadata import update_metadata
from ._post_helpers import (
    FIELD_DESCRIPTION,
    FIELD_ID,
    FIELD_INSTANCES,
    FIELD_INSTANCES_JSON,
    FIELD_NAME,
    FIELD_NEW_NAME,
    FIELD_NEW_SCENARIO_ID,
    FIELD_NGFW,
    FIELD_SCENARIO_ID,
    FIELD_SUBNETS,
    FIELD_SUBNETS_JSON,
    ScenarioFormFields,
    ScenarioYamlFields,
    clone_scenario_from_form_post,
    create_scenario_from_form_post,
    create_scenario_from_yaml_post,
    parse_scenario_form_fields,
    parse_yaml_create_fields,
    toggle_scenario_metadata_flag,
    update_scenario_from_form_post,
    update_scenario_from_yaml_post,
)
from ._validation import validate_definition, validate_yaml
from ._yaml import export_scenario_yaml, new_scenario_template_yaml

__all__ = [
    "FIELD_DESCRIPTION",
    "FIELD_ID",
    "FIELD_INSTANCES",
    "FIELD_INSTANCES_JSON",
    "FIELD_NAME",
    "FIELD_NEW_NAME",
    "FIELD_NEW_SCENARIO_ID",
    "FIELD_NGFW",
    "FIELD_SCENARIO_ID",
    "FIELD_SUBNETS",
    "FIELD_SUBNETS_JSON",
    "ScenarioEditorError",
    "ScenarioFormFields",
    "ScenarioYamlFields",
    "clone_scenario",
    "clone_scenario_from_form_post",
    "create_scenario",
    "create_scenario_from_form_post",
    "create_scenario_from_yaml_post",
    "delete_scenario",
    "export_scenario_yaml",
    "new_scenario_template_yaml",
    "parse_scenario_form_fields",
    "parse_yaml_create_fields",
    "toggle_scenario_metadata_flag",
    "update_metadata",
    "update_scenario",
    "update_scenario_from_form_post",
    "update_scenario_from_yaml_post",
    "validate_definition",
    "validate_yaml",
]
