"""Public Scenario Editor service API.

Implementation lives in responsibility-focused package modules. This facade
preserves the import path used by views and existing callers.
"""

from __future__ import annotations

from ._common import ScenarioEditorError
from ._crud import clone_scenario, create_scenario, delete_scenario, update_scenario
from ._metadata import update_metadata
from ._validation import validate_definition, validate_yaml
from ._yaml import export_scenario_yaml

__all__ = [
    "ScenarioEditorError",
    "clone_scenario",
    "create_scenario",
    "delete_scenario",
    "export_scenario_yaml",
    "update_metadata",
    "update_scenario",
    "validate_definition",
    "validate_yaml",
]
