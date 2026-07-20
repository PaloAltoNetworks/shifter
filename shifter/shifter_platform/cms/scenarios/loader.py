"""Scenario template loader.

Loads and validates YAML scenario templates from cms/scenarios/templates/.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from cms.scenarios.schema import AnyScenarioTemplate, ScenarioTemplate
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


def _normalize_scenario_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure legacy demo templates validate against the discriminated union."""
    if "scenario_type" not in data:
        return {**data, "scenario_type": "demo"}
    return data


_SCENARIO_ADAPTER: TypeAdapter[AnyScenarioTemplate] = TypeAdapter(AnyScenarioTemplate)


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
def load_scenario(scenario_id: str) -> AnyScenarioTemplate:
    """Load a scenario template by ID.

    Args:
        scenario_id: Unique scenario identifier (e.g., 'basic', 'ad_attack_lab')

    Returns:
        ScenarioTemplate: Validated scenario template (demo or CTF)

    Raises:
        ValueError: If scenario not found or template is invalid
    """
    scenario_id = _validate_scenario_id(scenario_id)
    logger.debug("load_scenario: scenario_id=%s", safe_log_value(scenario_id))

    # Resolve the template by a dict-key lookup over filesystem-enumerated
    # templates rather than constructing a path from the caller-supplied id. The
    # path handed to open() derives only from glob() output, so a user-controlled
    # id can never reach the filesystem sink even in principle -- defense-in-depth
    # on top of the slug allowlist, and the shape static analysis recognizes as
    # safe (path from a trusted enumeration, not tainted input). This is the
    # repo's canonical path-injection remediation: dict-key, not path.
    available = {path.stem: path for path in TEMPLATES_DIR.glob("*.yaml")}
    template_path = available.get(scenario_id)
    if template_path is None:
        logger.warning("load_scenario: not found scenario_id=%s", safe_log_value(scenario_id))
        raise ValueError(f"Scenario '{scenario_id}' not found")

    with open(template_path) as f:
        data = yaml.safe_load(f)

    logger.debug("load_scenario: loaded scenario_id=%s", safe_log_value(scenario_id))
    return _SCENARIO_ADAPTER.validate_python(_normalize_scenario_payload(data))


def load_demo_scenario(scenario_id: str) -> ScenarioTemplate:
    """Load a demo scenario template, rejecting CTF templates."""
    template = load_scenario(scenario_id)
    if not isinstance(template, ScenarioTemplate):
        raise ValueError(f"Scenario '{scenario_id}' is not a demo scenario")
    return template


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


def get_all_scenarios() -> list[AnyScenarioTemplate]:
    """Get all available scenarios.

    Returns:
        List of validated scenario templates (demo or CTF)
    """
    return [load_scenario(scenario_id) for scenario_id in list_scenario_ids()]
