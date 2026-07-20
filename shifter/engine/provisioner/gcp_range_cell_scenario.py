"""Scenario-owned compatibility adapter for legacy ``RangeSpec`` artifacts.

The GCP cell planner owns resources and lifecycle, not scenario classification.
This adapter is the sole compatibility seam that interprets legacy scenario
roles, image keys, guest access, and authored topology for that planner.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from shared.range_cells import RangeCellContractError, validate_gcp_vm_range_cell_request

from config import GCERangeCellConfig, GCERangeImageProfile, gce_image_profile_fingerprint
from executors.factory import get_ssh_username
from gcp_range_cell_naming import _network_tag, _short_resource_name

_DEFAULT_SSH_PORT = 22
_DOCKER_HOST_AMI_KEYS = frozenset({"polaris-vm"})
_DOCKER_HOST_SSH_USERNAME = "ubuntu"

ResourceDict = dict[str, Any]


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
    require_network_bindings: bool,
) -> ResourceDict:
    """Overlay platform CIDR bindings onto a defensive copy of legacy topology."""
    validated = validate_gcp_vm_range_cell_request(request)
    payload = deepcopy(validated["scenario_artifact"]["payload"])
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
    return config.get_profile(
        role=str(instance.get("role", "victim")),
        os_type=str(instance.get("os_type", instance.get("os", "ubuntu"))),
        ami_key=str(instance.get("ami_key") or ""),
    )


def _host_access(
    config: GCERangeCellConfig,
    instance: ResourceDict,
    os_type: str,
    role: str,
) -> tuple[str, str, int]:
    """Realize participant and setup access for a legacy scenario guest."""
    participant_user = get_ssh_username(os_type, role)
    if _is_docker_host(instance):
        return participant_user, _DOCKER_HOST_SSH_USERNAME, config.host_mgmt_ssh_port
    return participant_user, participant_user, _DEFAULT_SSH_PORT


def _is_docker_host(instance: ResourceDict) -> bool:
    """Return whether a guest is the host-side Polaris runtime that needs cloud APIs."""
    return str(instance.get("ami_key", "")).strip().lower() in _DOCKER_HOST_AMI_KEYS


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
            ssh_username, host_ssh_username, ssh_port = _host_access(config, instance, os_type, role)
            profile = _profile_for_instance(config, instance, require_images=require_images)
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
                    "attach_service_account": _is_docker_host(instance),
                }
            )
    return plans


__all__ = ["build_instance_plans", "realize_range_spec"]
