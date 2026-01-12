"""Scenario and NGFW hydration for Engine consumption.

Takes a scenario template + agent and produces a fully resolved
RangeSpec with:
- Resolved os_type (from_agent -> actual OS)
- Embedded agent details for instances with xdr_agent=True

Also provides NGFW hydration to extract credential data for provisioning.
"""

from __future__ import annotations

import logging
import uuid as uuid_module
from typing import TYPE_CHECKING, Literal

from cms.exceptions import CMSError
from shared.schemas import InstanceSpec, NGFWAppSpec, RangeSpec, SubnetSpec

from .loader import load_scenario

if TYPE_CHECKING:
    from cms.models import AgentConfig, App, Credential, Instance, Request

logger = logging.getLogger(__name__)


def hydrate_scenario(
    scenario_id: str,
    user_id: int,
    agents: dict[str, AgentConfig],
) -> RangeSpec:
    """Hydrate a scenario template with agent details.

    Args:
        scenario_id: ID of the scenario template (e.g., 'basic')
        user_id: ID of the user requesting the range
        agents: Mapping of OS type to AgentConfig, e.g. {"windows": agent, "linux": agent}

    Returns:
        RangeSpec with scenario_id, user_id, and hydrated subnets containing instances

    Raises:
        CMSError: If scenario not found or required agents missing
    """
    # Load scenario template
    try:
        template = load_scenario(scenario_id)
    except ValueError as e:
        logger.error("Scenario not found: scenario_id=%s", scenario_id)
        raise CMSError(f"Scenario '{scenario_id}' not found") from e

    # Validate agents if required by scenario
    if template.requires_agent() and not agents:
        logger.error(
            "hydrate_scenario: scenario=%s requires agent but none provided",
            scenario_id,
        )
        raise CMSError(f"Scenario '{scenario_id}' requires an agent")

    # Hydrate instances and build name→InstanceSpec mapping
    # Key is the template name (e.g., "Attacker") for subnet lookups
    instances_by_name: dict[str, InstanceSpec] = {}
    for instance in template.instances:
        try:
            hydrated = InstanceSpec.from_template(instance.model_dump(), agents)
            instances_by_name[instance.name] = hydrated
        except ValueError as e:
            raise CMSError(str(e)) from e

    # Build subnets from template, or create default if none defined
    subnets: list[SubnetSpec] = []
    if template.subnets:
        for subnet_config in template.subnets:
            try:
                hydrated_subnet = SubnetSpec.from_template(
                    subnet_config.model_dump(),
                    instances_by_name,
                )
                subnets.append(hydrated_subnet)
            except ValueError as e:
                raise CMSError(str(e)) from e
    else:
        # No subnets defined - create default subnet with all instances
        subnets.append(
            SubnetSpec(
                name="default",
                uuid=str(uuid_module.uuid4()),
                instances=list(instances_by_name.values()),
                connected_to=[],
            )
        )

    # Generate range UUID for cross-service correlation
    range_uuid = str(uuid_module.uuid4())

    logger.debug(
        "Hydrated scenario: scenario_id=%s, user_id=%s, subnets=%d, instances=%d, uuid=%s",
        scenario_id,
        user_id,
        len(subnets),
        len(instances_by_name),
        range_uuid,
    )

    return RangeSpec(
        uuid=range_uuid,
        scenario_id=scenario_id,
        user_id=user_id,
        subnets=subnets,
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
