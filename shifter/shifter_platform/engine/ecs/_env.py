"""GCP provisioner Job environment projection.

Forwards the runtime env-var contract that ephemeral GKE provisioner Jobs
need. Split out of the former single-module ``engine/ecs.py`` (#685); the
import path stays ``engine.ecs`` via the package facade.
"""

from __future__ import annotations

import os

from django.conf import settings

_GCP_PROVISIONER_ENV_KEYS = (
    "CLOUD_PROVIDER",
    "ENVIRONMENT",
    "CLOUD_REGION",
    "AWS_REGION",
    "GCP_REGION",
    "GCP_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUD_PROJECT_ID",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "FIELD_ENCRYPTION_KEY",
    "RANGE_EVENTS_TOPIC_ID",
    "SNS_RANGE_EVENTS_ARN",
    "STORAGE_BUCKET_NAME",
    "AGENT_STORAGE_BUCKET",
    "AGENT_S3_BUCKET",
    "RANGE_NETWORK_ID",
    "RANGE_NETWORK_CIDR",
    "RANGE_NETWORK_REGION",
    "RANGE_NETWORK_ZONE",
    "PORTAL_NETWORK_CIDRS",
    "GCP_RANGE_BACKEND",
    "GCP_RANGE_PLANE",
    "GCP_RANGE_CELL_NETWORK_MODE",
    "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL",
    "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
    "GCP_RANGE_LINUX_IMAGE",
    "GCP_RANGE_LINUX_MACHINE_TYPE",
    "GCP_RANGE_LINUX_DISK_SIZE_GB",
    "GCP_RANGE_LINUX_DISK_TYPE",
    "GCP_RANGE_KALI_IMAGE",
    "GCP_RANGE_KALI_MACHINE_TYPE",
    "GCP_RANGE_KALI_DISK_SIZE_GB",
    "GCP_RANGE_KALI_DISK_TYPE",
    "GCP_RANGE_WINDOWS_IMAGE",
    "GCP_RANGE_WINDOWS_MACHINE_TYPE",
    "GCP_RANGE_WINDOWS_DISK_SIZE_GB",
    "GCP_RANGE_WINDOWS_DISK_TYPE",
    "GCP_RANGE_DC_IMAGE",
    "GCP_RANGE_DC_MACHINE_TYPE",
    "GCP_RANGE_DC_DISK_SIZE_GB",
    "GCP_RANGE_DC_DISK_TYPE",
    "GCP_RANGE_EGRESS_ALLOW_CIDRS",
    "GCP_RANGE_PRIVATE_GOOGLE_ACCESS",
    "GCP_RANGE_HOST_MGMT_SSH_PORT",
    "GCP_RANGE_VERTEX_PROJECT_ID",
    "GCP_RANGE_VERTEX_REGION",
    "GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL",
    "GCP_RANGE_KALI_ANTHROPIC_MODEL",
    "GCP_RANGE_KALI_ANTHROPIC_SMALL_FAST_MODEL",
    "POLARIS_TESTS_BUCKET",
    "POLARIS_TESTS_KEY",
    "GDC_ACCESS_SECRET_ID",
    "GDC_RANGE_NAMESPACE_PREFIX",
    "GDC_NETWORK_INTERFACE",
    "GDC_NETWORK_DNS_NAMESERVERS",
    "GDC_STATIC_IP_RESERVATION_COUNT",
    "GDC_VM_STORAGE_CLASS",
    "GDC_VM_IMAGE_GCS_SECRET_ID",
    "GDC_VMSERIES_IMAGE_URL",
    "GDC_VMSERIES_BOOTSTRAP_BUCKET",
    "GDC_VMSERIES_STORAGE_CLASS",
    "GDC_VMSERIES_IMAGE_GCS_SECRET_ID",
    "GDC_VMSERIES_NAMESPACE_PREFIX",
    "GDC_VMSERIES_MGMT_NETWORK_NAME",
    "GDC_VMSERIES_MGMT_IP_CIDR",
    "GDC_VMSERIES_DATA_NETWORK_NAME",
    "GDC_VMSERIES_DATA_IP_CIDR",
    "GDC_VMSERIES_ROUTE_NEXT_HOP_IP",
    "GDC_VMSERIES_VCPUS",
    "GDC_VMSERIES_MEMORY",
    "GDC_VMSERIES_DISK_SIZE_GIB",
    "GDC_VMSERIES_BOOTSTRAP_DISK_SIZE_GIB",
    "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID",
    # GDC_WINDOWS_ADMIN_PASSWORD / GDC_KALI_PASSWORD / GDC_UBUNTU_PASSWORD
    # intentionally removed (#762). Guest passwords are now per-instance
    # GCP Secret Manager secrets created by the provisioner at apply
    # time and resolved by the portal through shared.cloud at access
    # time. No shared static credential flows through the provisioner
    # env any more.
    "DC_DOMAIN_PASSWORD",
    "GDC_KALI_IMAGE_URL",
    "GDC_KALI_VCPUS",
    "GDC_KALI_MEMORY",
    "GDC_KALI_DISK_SIZE_GIB",
    "GDC_UBUNTU_IMAGE_URL",
    "GDC_UBUNTU_VCPUS",
    "GDC_UBUNTU_MEMORY",
    "GDC_UBUNTU_DISK_SIZE_GIB",
    "GDC_WINDOWS_IMAGE_URL",
    "GDC_WINDOWS_VCPUS",
    "GDC_WINDOWS_MEMORY",
    "GDC_WINDOWS_DISK_SIZE_GIB",
    "GDC_DC_IMAGE_URL",
    "GDC_DC_VCPUS",
    "GDC_DC_MEMORY",
    "GDC_DC_DISK_SIZE_GIB",
    "GDC_SCENARIO_POD_IMAGE_PULL_POLICY",
    "GDC_SCENARIO_POD_KALI_IMAGE",
    "GDC_SCENARIO_POD_UBUNTU_IMAGE",
    # Image for the in-range-cluster guest setup-runner pod. GDC range VMs
    # live on an isolated L2 segment, so guest SSH setup runs from a pod in
    # the range cluster (RangePodSSHExecutor). GDC_SETUP_RUNNER_IMAGE is an
    # explicit override; otherwise the provisioner falls back to its own
    # image via ENGINE_TASK_IMAGE (forwarded here so it is set in the Job).
    "GDC_SETUP_RUNNER_IMAGE",
    "ENGINE_TASK_IMAGE",
    "RANGE_VPC_ID",
    "RANGE_VPC_CIDR",
    "RANGE_AVAILABILITY_ZONE",
    "AVAILABILITY_ZONE",
)


def _get_gcp_provisioner_env_overrides() -> dict[str, str] | None:
    """Forward the runtime env contract needed by ephemeral GKE provisioner Jobs."""
    if settings.CLOUD_PROVIDER != "gcp":
        return None

    fallback_values = {
        "CLOUD_PROVIDER": settings.CLOUD_PROVIDER,
        "ENVIRONMENT": getattr(settings, "ENVIRONMENT", ""),
        "CLOUD_REGION": getattr(settings, "CLOUD_REGION", ""),
        "AWS_REGION": getattr(settings, "AWS_REGION", ""),
        "GCP_REGION": os.environ.get("GCP_REGION") or getattr(settings, "CLOUD_REGION", ""),
        "GCP_PROJECT_ID": getattr(settings, "GCP_PROJECT_ID", ""),
        "GOOGLE_CLOUD_PROJECT": getattr(settings, "GCP_PROJECT_ID", ""),
        "CLOUD_PROJECT_ID": getattr(settings, "GCP_PROJECT_ID", ""),
    }

    env_overrides: dict[str, str] = {}
    for key in _GCP_PROVISIONER_ENV_KEYS:
        value = os.environ.get(key)
        if value is None or value == "":
            value = fallback_values.get(key, "")
        if value is None or value == "":
            continue
        env_overrides[key] = str(value)

    return env_overrides or None
