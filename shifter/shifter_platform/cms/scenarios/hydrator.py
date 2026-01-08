"""Scenario and NGFW hydration for Engine consumption.

Takes a scenario template + agent and produces a fully resolved
RangeSpec with:
- Resolved os_type (from_agent -> actual OS)
- Embedded agent details for instances with agent_slot

Also provides NGFW hydration to extract credential data for provisioning.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Literal, cast

from cms.exceptions import CMSError
from shared.schemas import AgentDetails, DCConfig, InstanceSpec, NGFWAppSpec, RangeSpec

from .loader import load_scenario

if TYPE_CHECKING:
    from cms.models import AgentConfig, App, Credential, Instance, Request
    from cms.scenarios.schema import InstanceConfig

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
    instance: InstanceConfig,
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
            sha256=agent.sha256_hash or "",
        )

    return InstanceSpec(
        name=f"{instance.role}-{os_type}",
        uuid=str(uuid.uuid4()),
        role=cast(Literal["attacker", "victim", "dc"], instance.role),
        os_type=cast(Literal["kali", "ubuntu", "windows"], os_type),
        agent=agent_details,
        dc_config=dc_config,
        join_domain=instance.join_domain,
    )


def hydrate_ngfw(
    instance: Instance,
    app: App,
    request: Request,
    deployment_profile: Credential,
    registration_method: Literal["pin", "otp"],
    scm_credential: Credential | None = None,
    otp_value: str | None = None,
    otp_folder: str | None = None,
) -> InstanceSpec:
    """Hydrate NGFW with credential data for Engine provisioning.

    Extracts actual credential values from Credential models and packages
    them into an InstanceSpec with nested NGFWAppSpec for Engine.

    Args:
        instance: CMS Instance model (provides UUID for event correlation).
        app: CMS App model (provides UUID for event correlation).
        request: CMS Request model (provides user context).
        deployment_profile: Deployment profile credential with authcode.
        registration_method: Either "pin" or "otp".
        scm_credential: SCM credential (required if registration_method="pin").
        otp_value: OTP value (required if registration_method="otp").
        otp_folder: OTP folder (required if registration_method="otp").

    Returns:
        InstanceSpec with hydrated NGFWAppSpec for Engine consumption.

    Raises:
        CMSError: If required credentials are missing or invalid.
    """
    # Validate deployment profile has authcode
    authcode = deployment_profile.data.get("authcode")
    if not authcode:
        logger.error(
            "hydrate_ngfw: deployment_profile id=%s missing authcode",
            deployment_profile.id,
        )
        raise CMSError("Deployment profile missing authcode")

    # Extract SCM data if PIN registration
    scm_folder_name: str | None = None
    scm_pin_id: str | None = None
    scm_pin_value: str | None = None
    sls_region: str | None = None

    if registration_method == "pin":
        if scm_credential is None:
            logger.error("hydrate_ngfw: PIN registration requires scm_credential")
            raise CMSError("SCM credential required for PIN registration")

        scm_data = scm_credential.data
        scm_folder_name = scm_data.get("scm_folder_name")
        scm_pin_id = scm_data.get("scm_pin_id")
        scm_pin_value = scm_data.get("scm_pin_value")
        sls_region = scm_data.get("sls_region")

        if not all([scm_folder_name, scm_pin_id, scm_pin_value]):
            logger.error(
                "hydrate_ngfw: scm_credential id=%s missing required fields",
                scm_credential.id,
            )
            raise CMSError("SCM credential missing required fields")

    elif registration_method == "otp" and (not otp_value or not otp_folder):
        logger.error("hydrate_ngfw: OTP registration requires otp_value/folder")
        raise CMSError("OTP value and folder required for OTP registration")

    logger.debug(
        "hydrate_ngfw: instance_id=%s, app_id=%s, method=%s",
        instance.id,
        app.id,
        registration_method,
    )

    # Create hydrated NGFWAppSpec with actual credential values
    ngfw_app = NGFWAppSpec(
        name=app.name,
        registration_method=registration_method,
        # Input fields (IDs) - optional for hydrated spec
        deployment_profile_id=deployment_profile.id,
        scm_credential_id=scm_credential.id if scm_credential else None,
        # Hydrated fields (actual values)
        instance_id=instance.id,
        app_id=app.id,
        user_id=request.user_id,
        authcode=authcode,
        scm_folder_name=scm_folder_name,
        scm_pin_id=scm_pin_id,
        scm_pin_value=scm_pin_value,
        sls_region=sls_region,
        otp_value=otp_value if registration_method == "otp" else None,
        otp_folder=otp_folder if registration_method == "otp" else None,
    )

    # Return InstanceSpec with nested NGFWAppSpec
    return InstanceSpec(
        name=app.name,
        uuid=str(instance.id),
        role="ngfw",
        os_type="panos",
        ngfw_app=ngfw_app,
    )
