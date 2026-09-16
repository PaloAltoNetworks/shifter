"""Provisioner Job environment projection (GKE and EKS).

Forwards the runtime env-var contract that ephemeral provisioner Jobs need. On
GCP the values ride ``_GCP_PROVISIONER_ENV_KEYS``; on AWS (#1826) the provisioner
now runs as a Kubernetes Job on EKS instead of an ECS task, so the contract that
used to be baked into the ECS task definition
(``platform/terraform/modules/engine-provisioner/task_definition.tf``) is
forwarded here as ``_AWS_PROVISIONER_ENV_KEYS`` from the platform runtime env.
Sensitive keys are separated into Secret-backed ``secretKeyRef`` env by the
neutral Job manifest builder via ``shared.cloud.sensitive_env`` — this module
only assembles the flat forwarded dict. Split out of the former single-module
``engine/ecs.py`` (#685); the import path stays ``engine.ecs`` via the package
facade.
"""

from __future__ import annotations

import os
from collections.abc import Collection

from django.conf import settings
from installation.runtime_inventory import AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS

_GCP_PROVISIONER_ENV_KEYS = (
    "CLOUD_PROVIDER",
    "ENVIRONMENT",
    "CLOUD_REGION",
    "AWS_REGION",
    "GCP_REGION",
    "GCP_PROJECT_ID",
    "GCP_DYNAMIC_SECRET_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUD_PROJECT_ID",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "FIELD_ENCRYPTION_KEY",
    "STORAGE_BUCKET_NAME",
    "AGENT_STORAGE_BUCKET",
    "AGENT_S3_BUCKET",
    "RANGE_NETWORK_ID",
    "RANGE_NETWORK_CIDR",
    "RANGE_NETWORK_REGION",
    "RANGE_NETWORK_ZONE",
    "PORTAL_NETWORK_CIDRS",
    "ACCESS_NETWORK_CIDRS",
    "GCP_PROVISIONER_SERVICE_ACCOUNT_EMAIL",
    "GCP_RANGE_BACKEND",
    "GCP_RANGE_PLANE",
    "GCP_RANGE_CELL_NETWORK_MODE",
    "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL",
    "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
    "GCP_RANGE_HOST_IDENTITY_POOL_SIZE",
    "GCP_RANGE_LINUX_IMAGE",
    "GCP_RANGE_LINUX_MACHINE_TYPE",
    "GCP_RANGE_LINUX_DISK_SIZE_GB",
    "GCP_RANGE_LINUX_DISK_TYPE",
    "GCP_RANGE_KALI_IMAGE",
    "GCP_RANGE_KALI_MACHINE_TYPE",
    "GCP_RANGE_KALI_DISK_SIZE_GB",
    "GCP_RANGE_KALI_DISK_TYPE",
    "GCP_RANGE_IMAGE_KEY_PROFILES_JSON",
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
    "GCP_RANGE_VERTEX_SHARED_KEY_SECRET_ID",
    "GCP_RANGE_PREPROVISIONED_FIREWALLS",
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


# AWS (EKS) provisioner Job env contract (#1826). The authoritative key set is
# the standalone bundle contract
# ``installation.runtime_inventory.AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS``
# (single source of truth; kept in lockstep with the AWS provisioner admission
# env allowlist in values-aws-*.yaml). It mirrors the environment the AWS
# provisioner used to receive from its ECS task definition; on EKS the
# provisioner runs as a Kubernetes Job and these are forwarded from the
# platform runtime env. DB_PASSWORD / FIELD_ENCRYPTION_KEY are intentionally
# absent (RDS IAM auth + entrypoint hydration); DC_DOMAIN_PASSWORD is the one
# Secret-backed env, routed to a secretKeyRef by shared.cloud.sensitive_env.
_AWS_PROVISIONER_ENV_KEYS = AWS_PROVISIONER_FORWARDED_RUNTIME_ENV_KEYS


def _forward_env(keys: Collection[str], fallback_values: dict[str, str]) -> dict[str, str] | None:
    """Forward ``keys`` from the process env, applying fallbacks and dropping empties."""
    env_overrides: dict[str, str] = {}
    for key in keys:
        value = os.environ.get(key)
        if value is None or value == "":
            value = fallback_values.get(key, "")
        if value is None or value == "":
            continue
        env_overrides[key] = str(value)
    return env_overrides or None


def _get_gcp_provisioner_env_overrides() -> dict[str, str] | None:
    """Forward the runtime env contract needed by ephemeral GKE provisioner Jobs."""
    if settings.CLOUD_PROVIDER != "gcp":
        return None

    # Only keys the GCP deployment contract actually defines may be fabricated
    # here. The provisioner-Job admission policy (restrict-provisioner-jobs)
    # requires every literal env entry to mirror a key of the runtime ConfigMap
    # with an identical value, so inventing a value the ConfigMap cannot carry
    # gets the whole Job denied -- not just that variable dropped.
    #
    # AWS_REGION is deliberately absent: scripts/gcp/render_runtime_env.py never
    # emits it, and settings.AWS_REGION still carries an AWS-shaped default on
    # GCP, so falling back to it forged an `AWS_REGION` literal that no GCP
    # ConfigMap contains and every provisioner Job was rejected. It stays in
    # _GCP_PROVISIONER_ENV_KEYS so a deployment that really does define it is
    # still forwarded (and then matches params.data); it is simply never
    # invented from settings.
    fallback_values = {
        "CLOUD_PROVIDER": settings.CLOUD_PROVIDER,
        "ENVIRONMENT": getattr(settings, "ENVIRONMENT", ""),
        "CLOUD_REGION": getattr(settings, "CLOUD_REGION", ""),
        "GCP_REGION": os.environ.get("GCP_REGION") or getattr(settings, "CLOUD_REGION", ""),
        "GCP_PROJECT_ID": getattr(settings, "GCP_PROJECT_ID", ""),
        "GCP_DYNAMIC_SECRET_PROJECT_ID": getattr(settings, "GCP_DYNAMIC_SECRET_PROJECT_ID", ""),
        "GOOGLE_CLOUD_PROJECT": getattr(settings, "GCP_PROJECT_ID", ""),
        "CLOUD_PROJECT_ID": getattr(settings, "GCP_PROJECT_ID", ""),
    }

    return _forward_env(_GCP_PROVISIONER_ENV_KEYS, fallback_values)


def _get_aws_provisioner_env_overrides() -> dict[str, str] | None:
    """Forward the runtime env contract needed by ephemeral EKS provisioner Jobs (#1826).

    Values come from the platform runtime env (the ``platform-runtime`` ConfigMap
    the launcher worker consumes), so each forwarded literal matches the ConfigMap
    the fail-closed admission policy validates the Job against. Fallbacks are
    limited to the three identity keys whose settings are the same source as the
    ConfigMap, so the forwarded value never diverges from what the policy expects.
    """
    if settings.CLOUD_PROVIDER != "aws":
        return None

    fallback_values = {
        "CLOUD_PROVIDER": settings.CLOUD_PROVIDER,
        "ENVIRONMENT": getattr(settings, "ENVIRONMENT", ""),
        "AWS_REGION": getattr(settings, "AWS_REGION", ""),
    }

    return _forward_env(_AWS_PROVISIONER_ENV_KEYS, fallback_values)


def _get_provisioner_env_overrides() -> dict[str, str] | None:
    """Return the provider-appropriate provisioner Job env overrides.

    Both AWS (EKS) and GCP (GKE) dispatch the provisioner as a Kubernetes Job and
    forward their runtime env contract here; each builder returns ``None`` when the
    active provider does not match, so exactly one contributes.
    """
    return _get_gcp_provisioner_env_overrides() or _get_aws_provisioner_env_overrides()
