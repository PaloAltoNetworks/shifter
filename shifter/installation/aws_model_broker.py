"""Private AWS broker deployment intent and strict applied-resource projection."""

from __future__ import annotations

import ipaddress
import json
import re
from typing import TYPE_CHECKING, Annotated, Any, Self, cast

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from shared.model_access.network import RFC1918_IPV4_NETWORKS

from .gcp_model_broker import (
    Hostname,
    ResourceName,
    _broker_catalog_projection,
    validate_broker_configmap_payload,
)
from .model_broker_runtime import project_broker_runtime, project_enrollment_env

if TYPE_CHECKING:
    from .schema import RootConfig


InvocationName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,23}$")]
RegionalModel = Annotated[str, Field(pattern=r"^anthropic\.[a-z0-9-]+-v[0-9]+:[0-9]+$", max_length=128)]
ROLE_PATTERN = r"arn:aws:iam::\d{12}:role/[A-Za-z0-9/+=,.@_-]+"


class AwsModelBrokerSettings(BaseModel):
    """Operator-owned endpoint and exact regional model inventory; never keys.

    Cross-region inference profiles require separate geography/IAM qualification.
    This transport admits regional Anthropic foundation models only.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    hostname: Hostname = ""
    admitted_subnets: list[str] = Field(default_factory=list, max_length=256)
    tls_secret_name: ResourceName = ""
    control_tls_secret_name: ResourceName = ""
    trust_configmap_name: ResourceName = ""
    invocation_models: dict[InvocationName, RegionalModel] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        populated = [value for key, value in self.model_dump().items() if key != "enabled"]
        if not self.enabled:
            if any(populated):
                raise ValueError("disabled broker cannot retain transport or invocation settings")
            return self
        if not all(populated):
            raise ValueError("enabled broker requires complete transport and invocation settings")
        _validate_admitted_subnets(self.admitted_subnets)
        if self.tls_secret_name == self.control_tls_secret_name:
            raise ValueError("broker and control require distinct TLS Secrets")
        return self


def _validate_admitted_subnets(admitted_subnets: list[str]) -> None:
    """Require disjoint private IPv4 subnets for guest broker admission."""
    networks = [ipaddress.IPv4Network(value, strict=True) for value in admitted_subnets]
    for index, network in enumerate(networks):
        if not any(network.subnet_of(private) for private in RFC1918_IPV4_NETWORKS) or any(
            network.overlaps(other) for other in networks[:index]
        ):
            raise ValueError("broker admission requires disjoint private IPv4 subnets")


def validate_aws_broker_intent(config: RootConfig) -> AwsModelBrokerSettings:
    """Reject unusable transport/accounting intent before Terraform mutation."""
    from .render import render_model_access_catalog, render_model_access_env

    settings = AwsModelBrokerSettings.model_validate(config.settings.get("model_broker", {}))
    if settings.enabled:
        catalog_json = render_model_access_catalog(config)
        projection = _broker_catalog_projection(catalog_json, render_model_access_env(config))
        control_env = cast(dict[str, str], projection["control_env"])
        if control_env["MODEL_ACCESS_ENABLED"] == "true":
            runtime = project_broker_runtime(
                config.settings.get("model_broker_runtime"), catalog_json=catalog_json, provider="aws"
            )
            targets = json.loads(runtime["providers_json"])["targets"]
            if {target["model"] for target in targets} != set(settings.invocation_models.values()) or any(
                target["region"] != config.settings["region"] for target in targets
            ):
                raise ValueError("broker intent must bind the configured regional models")
    return settings


def project_aws_model_broker(
    output: object,
    *,
    config: RootConfig,
    catalog_json: str,
    model_access_env: str,
    account_id: str,
) -> dict[str, Any]:
    """Bind intent, platform identity, native provider inventory and actual network."""
    settings = AwsModelBrokerSettings.model_validate(config.settings.get("model_broker", {}))
    if output is None and not settings.enabled:
        return {"enabled": False}
    if not isinstance(output, dict):
        raise ValueError("broker requires applied Terraform output")
    runtime_keys = _validate_output_settings(output, settings)
    if not settings.enabled:
        if any(output.get(key) for key in runtime_keys):
            raise ValueError("disabled broker cannot retain applied resources")
        return {"enabled": False}
    region = config.settings["region"]
    if output.get("region") != region:
        raise ValueError("broker readback belongs to another region")
    roles = _validate_identities(output, settings, account_id)
    _validate_network(output, region, account_id)
    result = settings.model_dump(mode="json", exclude={"invocation_models"})
    result.update({key: output[key] for key in runtime_keys - {"invocation_roles"}})
    result["identities_json"] = json.dumps(
        {"contract_version": "model-broker-identities/v1", "role_arn": output["role_arn"], "invocation_roles": roles},
        sort_keys=True,
        separators=(",", ":"),
    )
    result.update(_broker_catalog_projection(catalog_json, model_access_env))
    if result["control_env"]["MODEL_ACCESS_ENABLED"] == "true":
        _project_enabled_runtime(result, config, catalog_json, settings, roles, output)
    validate_broker_configmap_payload(
        result["catalog_json"],
        result["identities_json"] + result.get("providers_json", "") + json.dumps(result.get("enrollment_env", {})),
    )
    return result


def _project_enabled_runtime(
    result: dict[str, Any],
    config: RootConfig,
    catalog_json: str,
    settings: AwsModelBrokerSettings,
    roles: dict[str, str],
    output: dict[str, Any],
) -> None:
    """Project execution and enrollment only for the applied invocation inventory."""
    region = config.settings["region"]
    runtime = config.settings.get("model_broker_runtime")
    result.update(project_broker_runtime(runtime, catalog_json=catalog_json, provider="aws"))
    inventory = json.loads(result["providers_json"])["targets"]
    approved = {(roles[name], model) for name, model in settings.invocation_models.items()}
    if {(target["principal"], target["model"]) for target in inventory} != approved or any(
        target["region"] != region for target in inventory
    ):
        raise ValueError("provider targets differ from the applied regional invocation inventory")
    result["enrollment_env"] = project_enrollment_env(
        runtime, hostname=settings.hostname, guest_cidrs=output["guest_endpoint_cidrs"]
    )


def _validate_output_settings(output: dict[str, Any], settings: AwsModelBrokerSettings) -> set[str]:
    """Reject unknown or stale applied settings before inspecting cloud identities."""
    settings_keys = set(AwsModelBrokerSettings.model_fields)
    runtime_keys = {
        "role_arn",
        "provisioner_subject",
        "region",
        "invocation_roles",
        "target_group_arn",
        "vpc_id",
        "endpoint_cidrs",
        "guest_endpoint_cidrs",
        "health_check_cidrs",
    }
    if set(output) - settings_keys - runtime_keys:
        raise ValueError("unknown broker deployment output")
    if AwsModelBrokerSettings.model_validate({key: output[key] for key in settings_keys if key in output}) != settings:
        raise ValueError("broker Terraform readback differs from deployment intent")
    return runtime_keys


def _validate_identities(output: dict[str, Any], settings: AwsModelBrokerSettings, account_id: str) -> dict[str, str]:
    """Bind separate broker, provisioner and invocation roles to this account."""
    for key in ("role_arn", "provisioner_subject"):
        if (
            not re.fullmatch(ROLE_PATTERN, output.get(key, ""), flags=re.ASCII)
            or output[key].split(":")[4] != account_id
        ):
            raise ValueError("broker requires exact platform-account workload roles")
    if output["role_arn"] == output["provisioner_subject"]:
        raise ValueError("broker and provisioner roles must differ")
    roles = output.get("invocation_roles", {})
    if not isinstance(roles, dict) or set(roles) != set(settings.invocation_models):
        raise ValueError("applied invocation inventory differs from deployment intent")
    _validate_invocation_roles(roles, output, account_id)
    return roles


def _validate_invocation_roles(roles: dict[str, str], output: dict[str, Any], account_id: str) -> None:
    """Keep invocation identities distinct from one another and the platform roles."""
    if len(set(roles.values())) != len(roles) or any(
        not isinstance(role, str)
        or not re.fullmatch(ROLE_PATTERN, role, flags=re.ASCII)
        or role.split(":")[4] != account_id
        or role in {output["role_arn"], output["provisioner_subject"]}
        for role in roles.values()
    ):
        raise ValueError("invocation roles must be distinct platform-account identities")


def _validate_network(output: dict[str, Any], region: str, account_id: str) -> None:
    """Require a regional target group and exact private endpoint addresses."""
    if not re.fullmatch(
        rf"arn:aws:elasticloadbalancing:{re.escape(region)}:{account_id}:targetgroup/[a-zA-Z0-9-]+/[a-f0-9]+",
        output.get("target_group_arn", ""),
    ) or not re.fullmatch(r"vpc-[a-f0-9]+", output.get("vpc_id", "")):
        raise ValueError("invalid private broker target group")
    _validate_endpoint_cidrs(output)


def _validate_endpoint_cidrs(output: dict[str, Any]) -> None:
    """Require bounded private routes, with exact guest and broker endpoints."""
    for key in ("endpoint_cidrs", "health_check_cidrs", "guest_endpoint_cidrs"):
        values = output.get(key)
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError("broker requires bounded applied endpoint reachability")
        for value in values:
            network = ipaddress.IPv4Network(value, strict=True)
            if not any(network.subnet_of(private) for private in RFC1918_IPV4_NETWORKS) or (
                key != "health_check_cidrs" and network.prefixlen != 32
            ):
                raise ValueError("broker endpoint reachability must be private and exact")
