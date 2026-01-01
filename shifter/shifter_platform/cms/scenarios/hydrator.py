"""Scenario hydration for Engine consumption.

Takes a scenario template + agent and produces a fully resolved
range_config dict with:
- Resolved os_type (from_agent -> actual OS)
- Embedded agent details for instances with agent_slot
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cms.exceptions import CMSError

from .loader import load_scenario

if TYPE_CHECKING:
    from mission_control.models import AgentConfig

logger = logging.getLogger(__name__)


def hydrate_scenario(scenario_id: str, agent: AgentConfig | None) -> dict[str, Any]:
    """Hydrate a scenario template with agent details.

    Args:
        scenario_id: ID of the scenario template (e.g., 'basic', 'ad_attack_lab')
        agent: The agent to use for victim instances

    Returns:
        Dict with scenario_id and hydrated instances list:
        {
            "scenario_id": "basic",
            "instances": [
                {"role": "attacker", "os_type": "kali"},
                {"role": "victim", "os_type": "windows", "agent": {...}}
            ]
        }

    Raises:
        CMSError: If scenario not found or agent is None
    """
    # Validate agent
    if agent is None:
        logger.error("hydrate_scenario called with None agent for scenario=%s", scenario_id)
        raise CMSError("agent is required for scenario hydration")

    # Load scenario template
    try:
        template = load_scenario(scenario_id)
    except ValueError as e:
        logger.error("Scenario not found: scenario_id=%s", scenario_id)
        raise CMSError(f"Scenario '{scenario_id}' not found") from e

    # Resolve agent OS to instance os_type
    agent_os_type = _resolve_agent_os(agent)

    # Hydrate instances
    instances = []
    for instance in template.instances:
        hydrated = _hydrate_instance(instance, agent, agent_os_type)
        instances.append(hydrated)

    logger.debug(
        "Hydrated scenario: scenario_id=%s, instance_count=%d, agent_id=%s",
        scenario_id,
        len(instances),
        agent.id,
    )

    return {
        "scenario_id": scenario_id,
        "instances": instances,
    }


def _resolve_agent_os(agent: AgentConfig) -> str:
    """Map agent OS to provisioner os_type.

    Args:
        agent: The agent with OS info

    Returns:
        os_type string: 'windows' or 'ubuntu'
    """
    os_slug = agent.os.slug.lower()
    if os_slug == "windows":
        return "windows"
    # All Linux variants map to ubuntu
    return "ubuntu"


def _hydrate_instance(
    instance: Any,  # InstanceConfig from schema
    agent: AgentConfig,
    agent_os_type: str,
) -> dict[str, Any]:
    """Hydrate a single instance config.

    Args:
        instance: InstanceConfig from template
        agent: Agent to embed if instance has agent_slot
        agent_os_type: Resolved OS type from agent

    Returns:
        Hydrated instance dict
    """
    result: dict[str, Any] = {
        "role": instance.role,
        "os_type": instance.os_type if instance.os_type != "from_agent" else agent_os_type,
    }

    # Include DC config if present
    if instance.dc_config:
        result["dc_config"] = {
            "domain_name": instance.dc_config.domain_name,
            "netbios_name": instance.dc_config.netbios_name,
        }

    # Include join_domain if True
    if instance.join_domain:
        result["join_domain"] = True

    # Embed agent details if instance has agent_slot
    if instance.agent_slot:
        result["agent"] = {
            "s3_key": agent.s3_key,
            "filename": agent.original_filename,
            "sha256": agent.sha256_hash,
        }

    return result
