"""Scenario template loader.

Loads and validates YAML scenario templates from cms/scenarios/templates/.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

import yaml

from cms.scenarios.schema import ScenarioTemplate

logger = logging.getLogger(__name__)

# Directory containing scenario YAML templates
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Scenario IDs map directly to template filenames, so they must be a strict
# slug allowlist: this rejects path separators and ``..`` so a caller-supplied
# id cannot escape TEMPLATES_DIR (defense-in-depth against path traversal even
# though the URL ``<slug>`` converter already constrains the web entrypoint).
_SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$", re.IGNORECASE)


def _validate_scenario_id(scenario_id: str) -> str:
    """Return ``scenario_id`` if it is a safe slug, else raise ``ValueError``."""
    if not isinstance(scenario_id, str) or not _SCENARIO_ID_RE.match(scenario_id):
        raise ValueError("Invalid scenario id")
    return scenario_id


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
    scenario_id = _validate_scenario_id(scenario_id)
    logger.debug("load_scenario: scenario_id=%s", scenario_id)

    # Resolve the candidate path and confirm it stays inside TEMPLATES_DIR.
    # The slug validation already rejects traversal; this containment check is
    # the canonical path-traversal barrier (and what static analysis models).
    templates_root = TEMPLATES_DIR.resolve()
    template_path = (templates_root / f"{scenario_id}.yaml").resolve()
    if not template_path.is_relative_to(templates_root):
        raise ValueError("Invalid scenario id")

    if not template_path.exists():
        logger.warning("load_scenario: not found scenario_id=%s", scenario_id)
        raise ValueError(f"Scenario '{scenario_id}' not found")

    with open(template_path) as f:
        data = yaml.safe_load(f)

    logger.debug("load_scenario: loaded scenario_id=%s", scenario_id)
    return ScenarioTemplate(**data)


def list_scenario_ids() -> list[str]:
    """List all available scenario IDs.

    Returns:
        List of scenario IDs (derived from YAML filenames)
    """
    if not TEMPLATES_DIR.exists():
        logger.warning("list_scenario_ids: templates directory not found")
        return []

    ids = sorted([path.stem for path in TEMPLATES_DIR.glob("*.yaml")])
    logger.debug("list_scenario_ids: found %d scenarios", len(ids))
    return ids


def get_all_scenarios() -> list[ScenarioTemplate]:
    """Get all available scenarios.

    Returns:
        List of validated ScenarioTemplate objects
    """
    return [load_scenario(scenario_id) for scenario_id in list_scenario_ids()]
