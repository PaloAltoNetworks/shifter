"""Scenario template loader.

Loads and validates YAML scenario templates from cms/scenarios/templates/.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from cms.scenarios.schema import ScenarioTemplate

# Directory containing scenario YAML templates
TEMPLATES_DIR = Path(__file__).parent / "templates"


@lru_cache(maxsize=32)
def load_scenario(scenario_id: str) -> ScenarioTemplate:
    """Load a scenario template by ID.

    Args:
        scenario_id: Unique scenario identifier (e.g., 'basic', 'ad_attack_lab')

    Returns:
        ScenarioTemplate: Validated scenario template

    Raises:
        ValueError: If scenario not found or template is invalid
    """
    template_path = TEMPLATES_DIR / f"{scenario_id}.yaml"

    if not template_path.exists():
        raise ValueError(f"Scenario '{scenario_id}' not found")

    with open(template_path) as f:
        data = yaml.safe_load(f)

    return ScenarioTemplate(**data)


def list_scenario_ids() -> list[str]:
    """List all available scenario IDs.

    Returns:
        List of scenario IDs (derived from YAML filenames)
    """
    if not TEMPLATES_DIR.exists():
        return []

    return sorted([path.stem for path in TEMPLATES_DIR.glob("*.yaml")])


def get_all_scenarios() -> list[ScenarioTemplate]:
    """Get all available scenarios.

    Returns:
        List of validated ScenarioTemplate objects
    """
    return [load_scenario(scenario_id) for scenario_id in list_scenario_ids()]
