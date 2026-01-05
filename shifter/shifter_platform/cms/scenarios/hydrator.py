"""Scenario hydration for Engine consumption.

Takes a scenario template + agent and produces a fully resolved
RangeSpec with:
- Resolved os_type (from_agent -> actual OS)
- Embedded agent details for instances with agent_slot
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from cms.exceptions import CMSError
from shared.schemas import AgentDetails, DCConfig, InstanceSpec, RangeSpec

from .loader import load_scenario

if TYPE_CHECKING:
    from cms.models import AgentConfig

logger = logging.getLogger(__name__)


def hydrate_scenario(
    scenario_id: str,
    user_id: int,
    agent: AgentConfig | None,
) -> RangeSpec:
    """Hydrate a scenario template with agent details.

    Args:
        scenario_id: ID of the scenario template (e.g., 'basic')
        user_id: ID of the user requesting the range
        agent: The agent to use for victim instances

    Returns:
        RangeSpec with scenario_id, user_id, and hydrated instances

    Raises:
        CMSError: If scenario not found or agent is None
    """
    # Validate agent
    if agent is None:
        logger.error(
            "hydrate_scenario called with None agent for scenario=%s",
            scenario_id,
        )
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
    instances: list[InstanceSpec] = []
    for instance in template.instances:
        hydrated = _hydrate_instance(instance, agent, agent_os_type)
        instances.append(hydrated)

    logger.debug(
        "Hydrated scenario: scenario_id=%s, user_id=%s, instances=%d",
        scenario_id,
        user_id,
        len(instances),
    )

    return RangeSpec(
        scenario_id=scenario_id,
        user_id=user_id,
        instances=instances,
    )


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
    instance: object,  # InstanceConfig from schema
    agent: AgentConfig,
    agent_os_type: str,
) -> InstanceSpec:
    """Hydrate a single instance config.

    Args:
        instance: InstanceConfig from template
        agent: Agent to embed if instance has agent_slot
        agent_os_type: Resolved OS type from agent

    Returns:
        Hydrated InstanceSpec
    """
    # Resolve os_type
    os_type = instance.os_type if instance.os_type != "from_agent" else agent_os_type

    # Build DC config if present
    dc_config = None
    if instance.dc_config:
        dc_config = DCConfig(
            domain_name=instance.dc_config.domain_name,
            netbios_name=instance.dc_config.netbios_name,
        )

    # Build agent details if instance has agent_slot
    agent_details = None
    if instance.agent_slot:
        agent_details = AgentDetails(
            s3_key=agent.s3_key,
            filename=agent.original_filename,
            sha256=agent.sha256_hash,
        )

    return InstanceSpec(
        uuid=str(uuid.uuid4()),
        role=instance.role,
        os_type=os_type,
        agent=agent_details,
        dc_config=dc_config,
        join_domain=instance.join_domain,
    )
