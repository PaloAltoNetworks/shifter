"""Scenario-owned compatibility adapter for legacy ``RangeSpec`` artifacts.

The GCP cell planner owns resources and lifecycle, not scenario classification.
This adapter is the sole compatibility seam that interprets legacy scenario
roles, image keys, guest access, and authored topology for that planner.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from shared.range_cells import RangeCellContractError, validate_gcp_vm_range_cell_request
from shared.range_instantiation_policy import PREREQUISITE_DENIAL_CODE, UNSUPPORTED_CAPABILITY_CODE

from cloud.exceptions import CloudError
from config import (
    GCE_BOOTSTRAP_POLARIS_HOST,
    GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
    GCE_BOOTSTRAP_PREPROMOTED_DC,
    GCE_SUPPORTED_BOOTSTRAP_CAPABILITIES,
    GCERangeCellConfig,
    GCERangeImageProfile,
    gce_image_profile_fingerprint,
    load_gce_range_cell_config,
)
from executors.factory import get_ssh_username
from gcp_range_cell_naming import _network_tag, _short_resource_name
from gcp_range_host_identity import gcp_range_host_pool_service_account_email

_DEFAULT_SSH_PORT = 22
_DOCKER_HOST_SSH_USERNAME = "ubuntu"

ResourceDict = dict[str, Any]


def _unsupported_capability(message: str) -> CloudError:
    """Return an authored, stable failure for an unrealizable composition."""
    error = CloudError(message)
    error.code = UNSUPPORTED_CAPABILITY_CODE
    return error


def _missing_prerequisite(message: str) -> CloudError:
    """Return an authored, stable failure for missing realization inputs."""
    error = CloudError(message)
    error.code = PREREQUISITE_DENIAL_CODE
    return error


def _normalize_domain_dns_name(value: object) -> str:
    """Return a comparison form for one authored or configured DNS domain."""
    return str(value or "").strip().rstrip(".").casefold()


def _normalize_domain_netbios_name(value: object) -> str:
    """Return a comparison form for one authored or configured NetBIOS name."""
    return str(value or "").strip().casefold()


def _validate_domain_controller_profile(instance: ResourceDict, profile: GCERangeImageProfile) -> None:
    """Verify a domain controller profile against its authored domain identity."""
    dc_config = instance.get("dc_config")
    if not dc_config:
        return
    if not isinstance(dc_config, dict):
        raise RangeCellContractError("domain-controller dc_config must be an object")
    if profile.bootstrap_capability != GCE_BOOTSTRAP_PREPROMOTED_DC:
        raise _missing_prerequisite("A domain-controller composition requires a pre-promoted-domain GCE image profile")
    authored_dns_name = _normalize_domain_dns_name(dc_config.get("domain_name"))
    authored_netbios_name = _normalize_domain_netbios_name(dc_config.get("netbios_name"))
    configured_dns_name = _normalize_domain_dns_name(profile.domain_dns_name)
    configured_netbios_name = _normalize_domain_netbios_name(profile.domain_netbios_name)
    if (
        not authored_dns_name
        or not authored_netbios_name
        or authored_dns_name != configured_dns_name
        or authored_netbios_name != configured_netbios_name
    ):
        raise _missing_prerequisite(
            "The selected pre-promoted GCE domain image does not match the authored domain identity"
        )


def _validate_profile_capabilities(instance: ResourceDict, profile: GCERangeImageProfile) -> None:
    """Verify configured realization capabilities against authored guest intent."""
    if profile.bootstrap_capability not in GCE_SUPPORTED_BOOTSTRAP_CAPABILITIES:
        raise _unsupported_capability("The selected GCE image profile requires an unsupported bootstrap capability")
    if str(instance.get("role") or "").strip().lower() == "dc":
        _validate_domain_controller_profile(instance, profile)


def _validate_supported_composition(
    payload: ResourceDict,
    config: GCERangeCellConfig | None,
    backend: str | None,
) -> None:
    """Fail before provider mutation when the legacy shape is not GCE-realizable."""
    if payload.get("ngfw"):
        raise _unsupported_capability("The GCE VM range-cell backend does not support NGFW ranges")
    resolved_config = config
    for subnet in _require_resource_list(payload.get("subnets", []), "subnets"):
        for instance in _require_resource_list(subnet.get("instances", []), "instances"):
            if resolved_config is None:
                try:
                    resolved_config = load_gce_range_cell_config(backend=backend)
                except RuntimeError as exc:
                    raise _missing_prerequisite(str(exc)) from None
            profile = _profile_for_instance(resolved_config, instance, require_images=True)
            _validate_profile_capabilities(instance, profile)


def validate_legacy_gce_composition(
    scenario_artifact: ResourceDict,
    config: GCERangeCellConfig | None = None,
    *,
    backend: str | None = None,
) -> None:
    """Validate legacy scenario capabilities at the owning adapter boundary."""
    payload = scenario_artifact.get("payload")
    if not isinstance(payload, dict):
        raise RangeCellContractError("scenario_artifact.payload must be an object")
    _validate_supported_composition(deepcopy(payload), config, backend)


def _resource_dicts(value: object) -> list[ResourceDict]:
    """Return only mapping entries from a legacy resource list."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _require_resource_list(value: object, field: str) -> list[ResourceDict]:
    """Return a resource list or raise a field-specific contract error."""
    if not isinstance(value, list):
        raise RangeCellContractError(f"{field} must be a list")
    resources: list[ResourceDict] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise RangeCellContractError(f"{field}[{index}] must be an object")
        resources.append(item)
    return resources


def _collect_instance_refs(
    instances: list[ResourceDict],
    subnet_index: int,
    instance_refs: set[str],
) -> None:
    """Add unique authored member identities from one validated subnet."""
    for instance_index, instance in enumerate(instances):
        instance_ref = str(instance.get("uuid") or "").strip()
        if not instance_ref:
            raise RangeCellContractError(f"subnets[{subnet_index}].instances[{instance_index}] requires a uuid")
        if instance_ref in instance_refs:
            raise RangeCellContractError(f"duplicate authored instance uuid: {instance_ref}")
        instance_refs.add(instance_ref)


def _realize_subnets(
    payload: ResourceDict,
    bindings: dict[str, str],
    *,
    require_network_bindings: bool,
) -> tuple[list[ResourceDict], set[str], set[str]]:
    """Apply admitted CIDRs while validating authored subnet and member identities."""
    realized_subnets: list[ResourceDict] = []
    authored_refs: set[str] = set()
    instance_refs: set[str] = set()
    for subnet_index, subnet in enumerate(_require_resource_list(payload.get("subnets", []), "subnets")):
        subnet_name = str(subnet.get("name") or "").strip()
        subnet_ref = str(subnet.get("uuid") or "").strip()
        if not subnet_name or not subnet_ref:
            raise RuntimeError(f"GCE range subnet requires name and uuid: {subnet!r}")
        if subnet_ref in authored_refs:
            raise RangeCellContractError(f"duplicate authored subnet uuid: {subnet_ref}")
        authored_refs.add(subnet_ref)
        if require_network_bindings and subnet_ref not in bindings:
            raise RuntimeError(f"GCE range subnet requires a network binding to provision: {subnet_ref}")
        instances = _require_resource_list(subnet.get("instances", []), f"subnets[{subnet_index}].instances")
        _collect_instance_refs(instances, subnet_index, instance_refs)
        realized = deepcopy(subnet)
        realized["cidr"] = bindings.get(subnet_ref, "")
        realized["instances"] = deepcopy(instances)
        realized_subnets.append(realized)
    return realized_subnets, authored_refs, instance_refs


def _validate_access_declarations(
    validated: ResourceDict,
    payload: ResourceDict,
    instance_refs: set[str],
) -> list[ResourceDict]:
    """Verify outer participant access against digest-bound scenario intent."""
    access_declarations = deepcopy(validated["access_declarations"])
    artifact_declarations = payload.get("participant_access", [])
    outer_pairs = {(str(item["target_ref"]), str(item["channel"])) for item in access_declarations}
    artifact_pairs = {
        (str(item["target_ref"]), str(item["channel"]))
        for item in _require_resource_list(artifact_declarations, "participant_access")
    }
    if outer_pairs != artifact_pairs:
        raise RangeCellContractError("outer access declarations do not match the digest-bound scenario artifact")
    for declaration in access_declarations:
        target_ref = declaration["target_ref"]
        if target_ref not in instance_refs:
            raise RangeCellContractError(f"participant access references foreign authored member: {target_ref}")
    return access_declarations


def realize_range_spec(
    request: dict[str, object],
    *,
    config: GCERangeCellConfig,
    require_network_bindings: bool,
    require_supported_capabilities: bool = True,
) -> ResourceDict:
    """Overlay platform CIDR bindings onto a defensive copy of legacy topology."""
    validated = validate_gcp_vm_range_cell_request(request)
    payload = deepcopy(validated["scenario_artifact"]["payload"])
    if require_supported_capabilities:
        validate_legacy_gce_composition(validated["scenario_artifact"], config)
    bindings = {binding["subnet_ref"]: binding["cidr"] for binding in validated["network_bindings"]}
    realized_subnets, authored_refs, instance_refs = _realize_subnets(
        payload,
        bindings,
        require_network_bindings=require_network_bindings,
    )
    foreign_refs = sorted(set(bindings) - authored_refs)
    if foreign_refs:
        raise RangeCellContractError(f"network binding references foreign authored subnet: {foreign_refs[0]}")
    return {
        "range_id": validated["operation"]["range_id"],
        "subnets": realized_subnets,
        "access_declarations": _validate_access_declarations(validated, payload, instance_refs),
    }


def _profile_for_instance(
    config: GCERangeCellConfig,
    instance: ResourceDict,
    *,
    require_images: bool,
) -> GCERangeImageProfile:
    """Map legacy role/OS intent to a platform-approved GCE image profile."""
    if not require_images:
        return GCERangeImageProfile()
    try:
        return config.get_profile(
            role=str(instance.get("role", "victim")),
            os_type=str(instance.get("os_type", instance.get("os", "ubuntu"))),
            ami_key=str(instance.get("ami_key") or ""),
        )
    except RuntimeError as exc:
        raise _missing_prerequisite(str(exc)) from None


def _host_access(
    config: GCERangeCellConfig,
    profile: GCERangeImageProfile,
    os_type: str,
    role: str,
) -> tuple[str, str, int]:
    """Realize participant and setup access for a legacy scenario guest."""
    participant_user = get_ssh_username(os_type, role)
    if profile.bootstrap_capability == GCE_BOOTSTRAP_POLARIS_HOST:
        return participant_user, _DOCKER_HOST_SSH_USERNAME, config.host_mgmt_ssh_port
    if profile.bootstrap_capability == GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
        return profile.participant_username, profile.host_ssh_username, profile.host_ssh_port
    return participant_user, participant_user, _DEFAULT_SSH_PORT


def _range_host_service_account(
    config: GCERangeCellConfig,
    profile: GCERangeImageProfile,
    range_host_pool_slot: int | None,
) -> str:
    """Resolve a bounded pre-created identity for a preconfigured range host."""
    if profile.bootstrap_capability != GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
        return ""
    if range_host_pool_slot is None:
        raise _missing_prerequisite("A preconfigured GCE range host requires a range allocation slot")
    if range_host_pool_slot < 0 or config.range_host_identity_pool_size <= 0:
        raise _missing_prerequisite("The configured GCE range-host identity pool is disabled")
    identity_slot = range_host_pool_slot % config.range_host_identity_pool_size
    return gcp_range_host_pool_service_account_email(config.project_id, identity_slot)


def _instance_assignment_key(instance: ResourceDict, index: int) -> str:
    """Return the stable address-allocation key for a scenario instance."""
    return str(instance.get("uuid") or instance.get("name") or f"asset-{index}")


def build_instance_plans(
    *,
    range_id: int,
    config: GCERangeCellConfig,
    subnet_plans: list[ResourceDict],
    access_declarations: list[ResourceDict],
    require_images: bool,
    range_host_pool_slot: int | None = None,
) -> list[ResourceDict]:
    """Realize legacy scenario guests into provider-ready instance intents."""
    access_by_ref: dict[str, list[str]] = {}
    for declaration in access_declarations:
        access_by_ref.setdefault(str(declaration["target_ref"]), []).append(str(declaration["channel"]))
    plans: list[ResourceDict] = []
    for subnet_plan in subnet_plans:
        for index, instance in enumerate(_resource_dicts(subnet_plan["instances"])):
            key = _instance_assignment_key(instance, index)
            role = str(instance.get("role", "victim"))
            os_type = str(instance.get("os_type", instance.get("os", "ubuntu")))
            profile = _profile_for_instance(config, instance, require_images=require_images)
            ssh_username, host_ssh_username, ssh_port = _host_access(config, profile, os_type, role)
            service_account_email = _range_host_service_account(config, profile, range_host_pool_slot)
            image_key = str(instance.get("ami_key") or "").strip()
            resource_name = _short_resource_name(
                "shifter-r",
                range_id,
                subnet_plan["name"],
                instance.get("name") or instance.get("uuid") or index,
            )
            plans.append(
                {
                    "name": str(instance.get("name", "")).strip() or resource_name,
                    "uuid": str(instance.get("uuid", "")),
                    "resource_name": resource_name,
                    "address_name": _short_resource_name(resource_name, "ip"),
                    "subnet_name": subnet_plan["name"],
                    "subnet_resource_name": subnet_plan["resource_name"],
                    "subnetwork_link": subnet_plan["self_link"],
                    "private_ip": subnet_plan["ip_assignments"].get(key, ""),
                    "role": role,
                    "os_type": os_type,
                    "asset_type": "gce_vm",
                    "tags": [_network_tag(range_id), subnet_plan["tag"], _short_resource_name("shifter-role", role)],
                    "profile": profile,
                    "image_key": image_key,
                    "image_profile_fingerprint": gce_image_profile_fingerprint(profile) if require_images else "",
                    "source": instance,
                    "ssh_username": ssh_username,
                    "host_ssh_username": host_ssh_username,
                    "ssh_port": ssh_port,
                    "participant_access_channels": access_by_ref.get(str(instance.get("uuid", "")), []),
                    "attach_service_account": profile.bootstrap_capability == GCE_BOOTSTRAP_POLARIS_HOST,
                    "service_account_email": service_account_email,
                }
            )
    return plans


__all__ = ["build_instance_plans", "realize_range_spec"]
