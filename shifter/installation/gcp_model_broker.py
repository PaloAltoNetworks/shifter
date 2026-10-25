"""Deployment-owned GCP model broker transport intent; no policy or credentials."""

from __future__ import annotations

import ipaddress
import json
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from shared.model_access.network import RFC1918_IPV4_NETWORKS

if TYPE_CHECKING:
    from .schema import RootConfig

ProjectId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]
AccountId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")]
ResourceName = Annotated[str, Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$|^$")]
Hostname = Annotated[str, Field(pattern=r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$|^$", max_length=253)]
# A conservative budget below both ConfigMap's 1 MiB and client-side apply's
# 256 KiB annotation limit, including JSON escaping and fixed metadata.
MAX_BROKER_CONFIGMAP_PAYLOAD_BYTES = 96 * 1024


def validate_broker_configmap_payload(catalog_json: str, identities_json: str) -> None:
    """Account for both mounted documents before entering the Kubernetes lane."""
    if len(catalog_json.encode("utf-8")) + len(identities_json.encode("utf-8")) > MAX_BROKER_CONFIGMAP_PAYLOAD_BYTES:
        raise ValueError("model broker ConfigMap transport exceeds its 96 KiB payload budget")


class GcpModelBrokerSettings(BaseModel):
    """Closed transport configuration, provisioned only on explicit enablement.

    Model projects are pre-existing, deployment-owned choices and may include
    the platform project. The map values are stable invocation GSA account IDs,
    never credentials. This package creates identities and an endpoint, not
    active participant grants.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    hostname: Hostname = ""
    vip: str = ""
    admitted_subnets: list[str] = Field(default_factory=list, max_length=256)
    global_access: StrictBool = False
    tls_secret_name: ResourceName = ""
    control_tls_secret_name: ResourceName = ""
    trust_configmap_name: ResourceName = ""
    model_projects: dict[ProjectId, AccountId] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def validate_boundary(self) -> GcpModelBrokerSettings:
        """Fail incomplete or overlapping boundary intent before cloud mutation."""
        if not self.enabled:
            if any(
                (
                    self.hostname,
                    self.vip,
                    self.admitted_subnets,
                    self.global_access,
                    self.tls_secret_name,
                    self.control_tls_secret_name,
                    self.trust_configmap_name,
                    self.model_projects,
                )
            ):
                raise ValueError("disabled broker must not carry active transport or identity settings")
            return self
        if not all(
            (
                self.hostname,
                self.vip,
                self.admitted_subnets,
                self.tls_secret_name,
                self.control_tls_secret_name,
                self.trust_configmap_name,
                self.model_projects,
            )
        ):
            raise ValueError("enabled broker requires complete transport and model-project inventory")
        address = ipaddress.IPv4Address(self.vip)
        if not any(address in network for network in RFC1918_IPV4_NETWORKS):
            raise ValueError("broker VIP must be a private IPv4 address")
        networks = [ipaddress.IPv4Network(value, strict=True) for value in self.admitted_subnets]
        for index, network in enumerate(networks):
            if not any(network.subnet_of(private) for private in RFC1918_IPV4_NETWORKS):
                raise ValueError("admitted subnets must be private IPv4 networks")
            if address in network or any(network.overlaps(other) for other in networks[:index]):
                raise ValueError("admitted subnets must be disjoint from each other and the broker VIP")
        if self.tls_secret_name == self.control_tls_secret_name:
            raise ValueError("broker and Engine TLS references must be distinct")
        return self


BROKER_RUNTIME_ENV_KEYS = frozenset(
    {
        "MODEL_BROKER_IDENTITIES_PATH",
        "MODEL_BROKER_CATALOG_PATH",
        "MODEL_BROKER_CATALOG_DIGEST",
        "MODEL_BROKER_HOSTNAME",
        "MODEL_BROKER_CONTROL_URL",
        "MODEL_BROKER_CONTROL_AUDIENCE",
        "MODEL_BROKER_TLS_CERT",
        "MODEL_BROKER_TLS_KEY",
        "MODEL_BROKER_CA_FILE",
        "MODEL_BROKER_REGION",
        "MODEL_BROKER_PROVIDER",
        "MODEL_BROKER_PROVIDERS_PATH",
        "MODEL_PROVIDER_PROXY",
        "MODEL_BROKER_FINGERPRINT_KEY_PATH",
        "MODEL_BROKER_FINGERPRINT_KEY_VERSION",
        "MODEL_BROKER_FINGERPRINT_PREVIOUS_KEYS_PATH",
    }
)


def validate_model_broker_readback(output: object, config: RootConfig) -> None:
    """Bind both deployment adapters to current root intent and platform identity."""
    if config.backend != "gcp":
        raise ValueError("model broker deployment requires the GCP backend")
    settings = GcpModelBrokerSettings.model_validate(config.settings.get("model_broker", {}))
    if output is None:
        if settings.enabled:
            raise ValueError("enabled broker is missing applied Terraform output")
        return
    if not isinstance(output, dict):
        raise ValueError("invalid model broker deployment output")
    observed = {key: output[key] for key in GcpModelBrokerSettings.model_fields if key in output}
    if GcpModelBrokerSettings.model_validate(observed) != settings:
        raise ValueError("broker Terraform readback differs from root deployment intent")
    if settings.enabled and (
        output.get("region") != config.settings["region"]
        or not str(output.get("gsa", "")).endswith(f"@{config.settings['project_id']}.iam.gserviceaccount.com")
    ):
        raise ValueError("broker Terraform readback belongs to a different platform project or region")


def _broker_output_settings(output: dict[str, object]) -> GcpModelBrokerSettings:
    """Reject unexpected readback fields before extracting deployment settings."""
    settings_keys = set(GcpModelBrokerSettings.model_fields)
    if (
        set(output)
        - settings_keys
        - {"gsa", "model_identities", "region", "provisioner_subject", "broker_subject_id", "provisioner_subject_id"}
    ):
        raise ValueError("unknown model broker deployment output")
    return GcpModelBrokerSettings.model_validate({key: value for key, value in output.items() if key in settings_keys})


def _broker_identity_inventory(output: dict[str, object], settings: GcpModelBrokerSettings) -> dict[str, str]:
    """Bind runtime identity inventory to the exact configured model projects."""
    import json
    import re

    gsa = output.get("gsa", "")
    if not isinstance(gsa, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com", gsa
    ):
        raise ValueError("invalid broker workload identity")
    identities = {
        project: f"{account}@{project}.iam.gserviceaccount.com" for project, account in settings.model_projects.items()
    }
    if output.get("model_identities") != identities:
        raise ValueError("model identity output does not match the approved project inventory")
    region = output.get("region", "")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z]+-[a-z]+\d+", region, flags=re.ASCII):
        raise ValueError("broker requires a regional deployment")
    return {
        "gsa": gsa,
        "region": region,
        "identities_json": json.dumps(
            {"contract_version": "model-broker-identities/v1", "gsa": gsa, "model_identities": identities},
            separators=(",", ":"),
            sort_keys=True,
        ),
    }


def _broker_catalog_projection(catalog_json: str, model_access_env: str) -> dict[str, object]:
    """Normalize the bounded mounted catalog and bind its control environment."""
    import json

    from shared.model_access import load_catalog_json
    from shared.model_access.runtime import MAX_MODEL_ACCESS_CATALOG_BYTES

    from .model_access import DEFAULT_CATALOG_PATH

    if len(catalog_json.encode("utf-8")) > MAX_MODEL_ACCESS_CATALOG_BYTES:
        raise ValueError("broker catalog exceeds the maximum size")
    catalog = load_catalog_json(catalog_json)
    control_env = {}
    for line in model_access_env.splitlines():
        key, value = line.split("=", 1)
        control_env[key] = value
    expected_env = {
        "MODEL_ACCESS_ENABLED": control_env.get("MODEL_ACCESS_ENABLED"),
        "MODEL_ACCESS_CATALOG_PATH": DEFAULT_CATALOG_PATH,
        "MODEL_ACCESS_CATALOG_DIGEST": catalog.digest,
    }
    if control_env != expected_env or control_env.get("MODEL_ACCESS_ENABLED") not in {"true", "false"}:
        raise ValueError("control requires the canonical model-access environment bound to its catalog")
    if control_env["MODEL_ACCESS_ENABLED"] == "true" and not catalog.enabled:
        raise ValueError("enabled model access requires an enabled catalog")
    return {
        "control_env": control_env,
        "catalog_json": json.dumps(catalog.model_dump(mode="json"), separators=(",", ":"), sort_keys=True),
        "catalog_digest": catalog.digest,
    }


def _active_broker_identity(output: dict[str, object]) -> dict[str, str]:
    """Bind distinct applied GCP principals and immutable subject IDs."""
    import re

    subject = output.get("provisioner_subject", "")
    platform_project = str(output["gsa"]).partition("@")[2]
    if (
        not isinstance(subject, str)
        or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]@" + re.escape(platform_project), subject)
        or subject == output["gsa"]
    ):
        raise ValueError("active broker requires a distinct applied provisioner identity")
    identities = {"provisioner_subject": subject}
    for key in ("broker_subject_id", "provisioner_subject_id"):
        value = output.get(key, "")
        if not isinstance(value, str) or not re.fullmatch(r"\d{10,32}", value, flags=re.ASCII):
            raise ValueError("active broker requires applied immutable subject IDs")
        identities[key] = value
    if identities["broker_subject_id"] == identities["provisioner_subject_id"]:
        raise ValueError("broker and provisioner require distinct immutable subject IDs")
    return identities


def project_model_broker(
    output: object, *, catalog_json: str = "", model_access_env: str = "", runtime_settings: object = None
) -> dict[str, object]:
    """Validate Terraform readback and produce the sole broker Helm projection."""
    if output is None:
        return {"enabled": False}
    if not isinstance(output, dict):
        raise ValueError("invalid model broker deployment output")
    settings = _broker_output_settings(output)
    if not settings.enabled:
        if output.get("gsa") or output.get("model_identities"):
            raise ValueError("disabled broker cannot retain invocation identity")
        return {"enabled": False}
    result = settings.model_dump(mode="json", exclude={"model_projects"})
    result.update(_broker_identity_inventory(output, settings))
    result.update(_broker_catalog_projection(catalog_json, model_access_env))
    if result["control_env"]["MODEL_ACCESS_ENABLED"] == "true":
        from .model_broker_runtime import project_broker_runtime, project_enrollment_env

        result.update(_active_broker_identity(output))
        result.update(
            project_broker_runtime(
                runtime_settings, catalog_json=catalog_json, provider="gcp", model_identities=output["model_identities"]
            )
        )
        result["enrollment_env"] = project_enrollment_env(
            runtime_settings, hostname=result["hostname"], guest_vip=settings.vip
        )
    validate_broker_configmap_payload(
        result["catalog_json"],
        result["identities_json"] + result.get("providers_json", "") + json.dumps(result.get("enrollment_env", {})),
    )
    return result
