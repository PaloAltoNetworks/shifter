"""Native NGFW request hydration retained after the scenario-authoring archive."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from cms.exceptions import CMSError
from shared.log_sanitize import safe_log_value
from shared.schemas import InstanceSpec, NGFWAppSpec

if TYPE_CHECKING:
    from cms.models import App, Credential, Instance, Request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NGFWRegistration:
    """Deployment-profile and registration inputs for an NGFW request."""

    deployment_profile: Credential
    registration_method: Literal["pin", "otp"]
    scm_credential: Credential | None = None
    otp_value: str | None = None
    otp_folder: str | None = None


def hydrate_ngfw(
    instance: Instance,
    app: App,
    request: Request,
    registration: NGFWRegistration,
) -> InstanceSpec:
    """Resolve NGFW credential models into the provisioner contract."""
    deployment_profile = registration.deployment_profile
    authcode = deployment_profile.data.get("authcode")
    if not authcode:
        logger.error("hydrate_ngfw: deployment_profile id=%s missing authcode", deployment_profile.id)
        raise CMSError("Deployment profile missing authcode")

    scm_credential = registration.scm_credential
    scm_folder_name: str | None = None
    scm_pin_id: str | None = None
    scm_pin_value: str | None = None
    sls_region: str | None = None
    if registration.registration_method == "pin":
        if scm_credential is None:
            logger.error("hydrate_ngfw: PIN registration requires scm_credential")
            raise CMSError("SCM credential required for PIN registration")
        scm_data = scm_credential.data
        scm_folder_name = scm_data.get("scm_folder_name")
        scm_pin_id = scm_data.get("scm_pin_id")
        scm_pin_value = scm_data.get("scm_pin_value")
        sls_region = scm_data.get("sls_region")
        if not all([scm_pin_id, scm_pin_value]):
            logger.error("hydrate_ngfw: scm_credential id=%s missing required fields", scm_credential.id)
            raise CMSError("SCM credential missing required fields")
    elif registration.registration_method == "otp" and (not registration.otp_value or not registration.otp_folder):
        logger.error("hydrate_ngfw: OTP registration requires otp_value/folder")
        raise CMSError("OTP value and folder required for OTP registration")

    logger.debug(
        "hydrate_ngfw: instance_id=%s, app_id=%s, method=%s",
        instance.id,
        app.id,
        safe_log_value(registration.registration_method),
    )
    ngfw_app = NGFWAppSpec(
        name=app.name,
        registration_method=registration.registration_method,
        deployment_profile_id=deployment_profile.id,
        scm_credential_id=scm_credential.id if scm_credential else None,
        instance_id=instance.id,
        app_id=app.id,
        user_id=request.user_id,
        authcode=authcode,
        scm_folder_name=scm_folder_name,
        scm_pin_id=scm_pin_id,
        scm_pin_value=scm_pin_value,
        sls_region=sls_region,
        otp_value=registration.otp_value if registration.registration_method == "otp" else None,
        otp_folder=registration.otp_folder if registration.registration_method == "otp" else None,
    )
    return InstanceSpec(
        name=app.name,
        uuid=str(instance.id),
        role="ngfw",
        os_type="panos",
        ngfw_app=ngfw_app,
    )
