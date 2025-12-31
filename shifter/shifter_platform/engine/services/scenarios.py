"""Scenario configuration and validation service.

This module handles:
- Scenario instance configuration generation
- Launch request validation (agent ownership, scenario constraints)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mission_control.models import AgentConfig

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class ScenarioValidationError(Exception):
    """Validation error for scenario/launch requests.

    Attributes:
        status_code: HTTP status code to return (400, 404, etc.)
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def get_scenario_config(scenario: str, agent_os: str) -> list:
    """Get instance configuration for a scenario.

    Args:
        scenario: Scenario identifier (basic, ad_attack_lab)
        agent_os: Operating system from agent (linux, windows)

    Returns:
        List of instance configuration dicts for the provisioner
    """
    # Map agent OS names to provisioner os_type
    match agent_os.lower():
        case "windows":
            os_type = "windows"
        case _:
            os_type = "ubuntu"

    # Instance types are not specified here - the provisioner uses
    # its catalog defaults from environment variables
    scenarios = {
        "basic": [
            {"role": "attacker", "os_type": "kali"},
            {"role": "victim", "os_type": os_type},
        ],
        "ad_attack_lab": [
            {"role": "attacker", "os_type": "kali"},
            {
                "role": "dc",
                "os_type": "windows",
                "dc_config": {"domain_name": "shifter.local", "netbios_name": "SHIFTER"},
            },
            {
                "role": "victim",
                "os_type": "windows",
                "join_domain": True,
            },
        ],
    }

    return scenarios.get(scenario, scenarios["basic"])


def validate_launch(user: User, agent_id: int, scenario: str) -> tuple[AgentConfig, AgentConfig | None]:
    """Validate a range launch request.

    Validates:
    - Agent exists and belongs to user
    - Agent is not soft-deleted
    - Scenario constraints are met (e.g., AD requires Windows)

    Args:
        user: The requesting user
        agent_id: ID of the agent to use
        scenario: Scenario identifier

    Returns:
        Tuple of (agent, dc_agent). dc_agent is None for non-AD scenarios,
        or the same as agent for AD scenarios (same agent used for DC and victim).

    Raises:
        ScenarioValidationError: If validation fails
    """
    # Verify agent belongs to user and is not deleted
    agent = AgentConfig.active_for_user(user).filter(id=agent_id).select_related("os").first()

    if not agent:
        raise ScenarioValidationError("Agent not found", status_code=404)

    # Handle agent validation for AD scenarios
    dc_agent = None

    if scenario == "ad_attack_lab":
        # AD scenario requires Windows agent (used for both DC and victim)
        if agent.os.slug != "windows":
            raise ScenarioValidationError(
                "AD Attack Lab requires a Windows (MSI) agent. Both DC and victim are Windows.",
                status_code=400,
            )
        # Use same agent for DC and victim
        dc_agent = agent

    return agent, dc_agent
