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
