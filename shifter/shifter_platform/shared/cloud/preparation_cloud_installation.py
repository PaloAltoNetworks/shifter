"""Terraform JSON for an optional, separately managed preparation installation.

This is infrastructure configuration, never an application-side IAM mutation.
The operator applies it in dedicated remote state and reviews the Terraform plan.
IAM constrains resource access; approved immutable executables enforce recipes,
VM sizes and operation labels which Compute IAM cannot express as conditions.
"""

from typing import Any

from shared.cloud.preparation_installation import PreparationInstallation

_SERVICE_ACCOUNT_REFERENCE = "${google_service_account."

READ_PERMISSIONS = [
    "compute.instances.get",
    "compute.instances.list",
    "compute.disks.get",
    "compute.disks.list",
    "compute.images.get",
    "compute.images.list",
    "compute.zoneOperations.get",
    "compute.zoneOperations.list",
    "compute.globalOperations.get",
    "compute.globalOperations.list",
]
GUEST_PERMISSIONS = [
    "compute.instances.setMetadata",
    "compute.instances.setTags",
    "compute.instances.setLabels",
    "compute.instances.getSerialPortOutput",
    "compute.disks.setLabels",
    "compute.disks.use",
    "compute.disks.useReadOnly",
]
PERMISSIONS = {
    "read": READ_PERMISSIONS,
    "builder_create": ["compute.instances.create", "compute.disks.create", "compute.images.create"],
    "verifier_create": ["compute.instances.create", "compute.disks.create"],
    "builder_mutate": [*GUEST_PERMISSIONS, "compute.images.setLabels"],
    "verifier_mutate": [*GUEST_PERMISSIONS, "compute.instances.attachDisk"],
    "cleanup_mutate": ["compute.instances.delete", "compute.disks.delete", "compute.images.delete"],
    "image_use": ["compute.images.useReadOnly"],
    "subnet_use": ["compute.subnetworks.use", "compute.subnetworks.get"],
}


def role_name(configuration: PreparationInstallation, key: str) -> str:
    """Handle role name."""
    return f"projects/{configuration.grant.project_id}/roles/shifterPrep{configuration.grant.scope_digest[-12:]}_{key}"


def owned_condition(configuration: PreparationInstallation) -> dict[str, str]:
    """Handle owned condition."""
    grant = configuration.grant
    stems = [f"projects/{grant.project_id}/zones/{grant.zone}/{kind}/prep-" for kind in ("instances", "disks")]
    stems.append(f"projects/{grant.project_id}/global/images/prep-")
    return {
        "title": "preparation_resources",
        "expression": " || ".join(f"resource.name.startsWith('{stem}')" for stem in stems),
    }


def workload_member(configuration: PreparationInstallation, role: str) -> str:
    """Handle workload member."""
    grant = configuration.grant
    namespace = configuration.platform_namespace if role == "controller" else grant.namespace
    account = configuration.controller_name if role == "controller" else getattr(grant, role + "_service_account")
    return f"serviceAccount:{grant.project_id}.svc.id.goog[{namespace}/{account}]"


def cloud_bindings(
    configuration: PreparationInstallation,
) -> dict[str, tuple[str, str, dict[str, str] | None]]:
    """The same exact role/condition contract drives rendering and cloud readback."""
    bindings: dict[str, tuple[str, str, dict[str, str] | None]] = {}
    for actor in configuration.service_accounts:
        bindings[actor + "_read"] = (actor, "read", None)
        if actor != "controller":
            bindings[actor + "_mutate"] = (actor, actor + "_mutate", owned_condition(configuration))
        if actor in {"builder", "verifier"}:
            bindings[actor + "_create"] = (actor, actor + "_create", None)
            # Images outside this project retain their publisher's separate IAM.
            # Public images and privately shared images both require that grant.
            condition = owned_condition(configuration)
            images = sorted({configuration.grant.scanner_image, *configuration.input_images})
            condition = dict(
                condition,
                expression=condition["expression"]
                + " || "
                + " || ".join(f"resource.name == '{image}'" for image in images),
            )
            bindings[actor + "_image_use"] = (actor, "image_use", condition)
    return bindings


def render_preparation_terraform(configuration: PreparationInstallation) -> dict[str, Any]:
    """Produce a native .tf.json root; Terraform owns apply, state, drift and teardown."""
    grant = configuration.grant
    region = grant.zone.rsplit("-", 1)[0]
    network_name = grant.subnetwork.rsplit("/", 1)[1]
    resources: dict[str, dict[str, Any]] = {
        "google_service_account": {
            role: {
                "project": grant.project_id,
                "account_id": email.split("@", 1)[0],
                "display_name": "Shifter preparation " + role,
            }
            for role, email in configuration.service_accounts.items()
        },
        "google_service_account_iam_binding": {
            role: {
                "service_account_id": _SERVICE_ACCOUNT_REFERENCE + role + ".name}",
                "role": "roles/iam.workloadIdentityUser",
                "members": [workload_member(configuration, role)],
            }
            for role in configuration.service_accounts
        },
        "google_project_iam_custom_role": {
            key: {
                "project": grant.project_id,
                "role_id": role_name(configuration, key).rsplit("/", 1)[1],
                "title": "Shifter preparation " + key,
                "permissions": permissions,
                "stage": "GA",
            }
            for key, permissions in PERMISSIONS.items()
        },
        "google_project_iam_member": {},
        "google_compute_network": {
            "preparation": {
                "project": grant.project_id,
                "name": network_name,
                "auto_create_subnetworks": False,
                "routing_mode": "REGIONAL",
                "delete_default_routes_on_create": True,
            }
        },
        "google_compute_subnetwork": {
            "preparation": {
                "project": grant.project_id,
                "region": region,
                "name": network_name,
                "network": "${google_compute_network.preparation.id}",
                "ip_cidr_range": configuration.network_cidr,
                "private_ip_google_access": False,
            }
        },
        "google_compute_firewall": {
            "probe": {
                "project": grant.project_id,
                "name": network_name[:57] + "-http",
                "network": "${google_compute_network.preparation.id}",
                "direction": "INGRESS",
                "source_tags": ["shifter-preparation"],
                "target_tags": ["shifter-preparation"],
                "allow": [{"protocol": "tcp", "ports": ["8080"]}],
            }
        },
        "google_compute_subnetwork_iam_member": {
            role: {
                "project": grant.project_id,
                "region": region,
                "subnetwork": "${google_compute_subnetwork.preparation.name}",
                "role": "${google_project_iam_custom_role.subnet_use.name}",
                "member": _SERVICE_ACCOUNT_REFERENCE + role + ".member}",
            }
            for role in ("builder", "verifier")
        },
        "google_secret_manager_secret_iam_member": {
            key.lower(): {
                "project": grant.project_id,
                "secret_id": secret,
                "role": "roles/secretmanager.secretAccessor",
                "member": "${google_service_account.controller.member}",
            }
            for key, secret in configuration.controller_secret_ids.items()
        },
    }
    for name, (actor, key, condition) in cloud_bindings(configuration).items():
        binding: dict[str, Any] = {
            "project": grant.project_id,
            "role": "${google_project_iam_custom_role." + key + ".name}",
            "member": _SERVICE_ACCOUNT_REFERENCE + actor + ".member}",
        }
        if condition:
            binding["condition"] = [condition]
        resources["google_project_iam_member"][name] = binding
    return {
        "terraform": {
            "required_version": ">= 1.7, < 2.0",
            "backend": {"gcs": {}},
            "required_providers": {"google": {"source": "hashicorp/google", "version": "~> 8.1"}},
        },
        "provider": {"google": {"project": grant.project_id, "region": region}},
        "resource": resources,
        "output": {"installation_digest": {"value": configuration.digest}},
    }
