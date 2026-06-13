"""Scenario YAML serialization."""

from __future__ import annotations

import logging

import yaml

from cms.scenarios.registry import get_scenario_detail
from shared.log_sanitize import safe_log_value

from ._common import ScenarioEditorError

logger = logging.getLogger(__name__)


def export_scenario_yaml(scenario_id: str) -> str:
    """Export a scenario as YAML without metadata overlay fields."""
    logger.debug("export_scenario_yaml called for scenario_id=%s", safe_log_value(scenario_id))

    try:
        data = get_scenario_detail(scenario_id)
    except ValueError as e:
        logger.error(
            "export_scenario_yaml: scenario not found, scenario_id=%s",
            safe_log_value(scenario_id),
        )
        raise ScenarioEditorError(f"Scenario '{scenario_id}' not found") from e

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
