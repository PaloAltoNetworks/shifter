"""Configuration module for Shifter Engine.

This module handles configuration dataclasses, database access,
and utility functions for the provisioner.
"""

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


def decrypt_field(encrypted_value: str) -> str:
    """Decrypt a Fernet-encrypted field value.

    Used for sensitive fields that are encrypted at rest in the Django
    database using django-encrypted-model-fields.

    Args:
        encrypted_value: Base64-encoded Fernet ciphertext from database

    Returns:
        Decrypted plaintext string

    Raises:
        ValueError: If FIELD_ENCRYPTION_KEY not set or decryption fails
    """
    if not encrypted_value:
        return ""

    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        logger.warning("FIELD_ENCRYPTION_KEY not set, returning value as-is")
        return encrypted_value

    try:
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode("ascii"))
        return fernet.decrypt(encrypted_bytes).decode("utf-8")
    except Exception as e:
        # If decryption fails, log and return as-is (for backward compatibility)
        logger.warning(f"Failed to decrypt field: {e}")
        return encrypted_value


def generate_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for an S3 object.

    Delegates to the cloud abstraction layer's ObjectStorage implementation.

    This is called during config loading (before provisioning), not during
    resource creation. It's safe because it doesn't create any AWS resources.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        expires_in: URL expiration time in seconds.

    Returns:
        Presigned URL string.
    """
    from cloud import get_object_storage

    storage = get_object_storage()
    return storage.generate_presigned_download_url(bucket=bucket, key=key, expires_in=expires_in)


@dataclass
class InstanceConfig:
    """Configuration for an instance to be provisioned.

    Attributes:
        uuid: Unique identifier from the spec (for tagging and DB correlation).
        name: Display name for UI (e.g., "target-ubuntu", "attacker-kali").
        role: Instance role ("attacker", "victim", or "dc").
        os_type: Operating system type ("kali", "ubuntu", "windows").
        instance_type: AWS instance type (e.g., "t3.medium").
        agent_s3_key: S3 key for agent installer (optional).
        agent_presigned_url: Presigned URL for agent download (optional).
        dc_config: Domain controller configuration (optional).
        join_domain: Whether this instance should join a domain.
        dc_config_param_name: SSM parameter path for DC config (optional).
    """

    uuid: str  # Required: correlation key for tagging and DB updates
    name: str  # Display name like "target-ubuntu" or "attacker-kali"
    role: str  # "attacker", "victim", or "dc"
    os_type: str  # "kali", "ubuntu", "windows"
    instance_type: str
    agent_s3_key: str | None = None  # S3 key for agent installer
    agent_presigned_url: str | None = None  # Presigned URL for agent download
    dc_config: dict[str, str] | None = None  # {"domain_name": "...", "netbios_name": "..."}
    join_domain: bool = False  # Whether this instance should join a domain
    dc_config_param_name: str | None = None  # SSM parameter path for DC config


@dataclass
class SubnetConfig:
    """Configuration for a logical subnet and its instances.

    A logical subnet groups instances that share network visibility.
    Each SubnetConfig becomes one AWS /28 subnet during provisioning.

    Attributes:
        name: Subnet name (e.g., 'attack', 'dc_network').
        uuid: Unique identifier for tagging and correlation.
        instances: List of instances in this subnet.
        connected_to: List of subnet names this subnet needs to reach.
    """

    name: str
    uuid: str
    instances: list[InstanceConfig]
    connected_to: list[str] = field(default_factory=list)


@dataclass
class RangeConfig:
    """Configuration for a complete range.

    Attributes:
        range_id: Database ID for the range.
        user_id: Owner's user ID.
        request_uuid: Correlation key for the provisioning request.
        environment: Deployment environment (dev, staging, prod).
        subnets: List of logical subnets with their instances.
        vpc_id: AWS VPC ID for range deployment.
        vpc_cidr: VPC CIDR block (e.g., '10.1.0.0/16').
        ngfw_data_eni_id: Legacy AWS data ENI ID for inter-subnet routing.
            Empty string if no AWS NGFW attachment is present.
    """

    range_id: int
    user_id: int
    request_uuid: str
    environment: str
    subnets: list[SubnetConfig]
    vpc_id: str
    vpc_cidr: str
    route_table_id: str
    instance_profile_name: str
    kali_ami_id: str
    victim_ami_id: str
    windows_ami_id: str
    agent_s3_bucket: str
    availability_zone: str
    ngfw_data_eni_id: str = ""  # Legacy AWS data ENI ID for inter-subnet routing
    ngfw_attachment_mode: str = ""  # Provider-neutral NGFW attachment mode
    ngfw_route_next_hop_ip: str = ""  # Provider-neutral next hop used for subnet routes
    dc_ami_id: str = ""  # AMI ID for DC instances (prebaked with AD DS)
    portal_vpc_cidr: str = ""
    portal_vpc_peering_id: str = ""  # VPC peering connection ID for portal route
    # NGFW (VM-Series) configuration
    ngfw_enabled: bool = False
    ngfw_ami_id: str = ""
    ngfw_instance_type: str = "m5.xlarge"
    # NGFW connection info for subnet configuration (set when ngfw_enabled=True)
    ngfw_management_ip: str = ""  # NGFW management IP for SSH
    ngfw_ssh_key_secret_arn: str = ""  # Secrets Manager ARN for SSH private key
    ngfw_subnet_cidr: str = ""  # NGFW subnet CIDR for computing gateway IP
    # S3 VPC endpoint for agent downloads (Gateway endpoint ID)
    s3_endpoint_id: str = ""
    # AWS Network Firewall endpoint ID for internet egress from range subnets
    firewall_endpoint_id: str = ""
    # SSM/Bedrock endpoints subnet CIDR for NGFW routing
    ssm_endpoints_subnet_cidr: str = ""


@dataclass(frozen=True)
class RangeNetworkConfig:
    """Provider-neutral network contract for range provisioning.

    This keeps the provisioner's subnet allocation and future Terraform inputs
    behind generic env names while preserving the legacy AWS VPC env vars as
    fallbacks.
    """

    network_id: str
    network_cidr: str
    network_region: str
    portal_network_cidrs: tuple[str, ...] = ()

    @property
    def primary_portal_cidr(self) -> str:
        """Return the first portal CIDR for legacy single-CIDR call sites."""
        return self.portal_network_cidrs[0] if self.portal_network_cidrs else ""


@dataclass(frozen=True)
class GDCNetworkAccessConfig:
    """Access contract for the GDC VM Runtime range plane."""

    access_secret_id: str
    kubeconfig: str
    cluster_id: str
    vxlan_cidr: str
    region: str
    namespace_prefix: str = "range"
    network_interface: str = "vxlan0"
    dns_nameservers: tuple[str, ...] = ("8.8.8.8",)
    static_ip_reservation_count: int = 4


@dataclass(frozen=True)
class GDCVMRuntimeProfile:
    """Per-guest VM Runtime sizing configuration.

    The image URL is no longer stored on the profile. It is fetched at
    range-create time from Secret Manager via
    :func:`main.get_gdc_image_url`, mirroring the AWS SSM-backed
    :func:`main.get_ami_id` contract so image rotations do not require a
    portal redeploy.
    """

    vcpus: int = 1
    memory: str = "2Gi"
    disk_size_gib: int = 20


@dataclass(frozen=True)
class GDCVMRuntimeConfig:
    """VM Runtime sizing contract for the active GCP range plane."""

    storage_class_name: str = "local-shared"
    image_gcs_secret_id: str = ""
    kali: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)
    ubuntu: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)
    windows: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)
    dc: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)

    def get_profile(self, *, role: str, os_type: str) -> GDCVMRuntimeProfile:
        """Return the matching VM Runtime sizing profile for a scenario instance."""
        if role == "dc":
            return self.dc
        if os_type == "kali":
            return self.kali
        if os_type == "windows":
            return self.windows
        return self.ubuntu


@dataclass(frozen=True)
class GDCPaloAltoVMSeriesConfig:
    """Palo Alto VM-Series VM Runtime contract for the active GCP NGFW path.

    The VM-Series image URL is not stored here. It is fetched at NGFW
    provisioning time via ``main.get_gdc_image_url("vmseries")`` so image
    rotations track the same Secret Manager contract as the range VM images.
    """

    bootstrap_bucket: str
    storage_class_name: str = "local-shared"
    image_gcs_secret_id: str = ""
    namespace_prefix: str = "ngfw"
    management_network_name: str = "pod-network"
    management_ip_cidr: str = ""
    data_network_name: str = ""
    data_ip_cidr: str = ""
    route_next_hop_ip: str = ""
    vcpus: int = 4
    memory: str = "8Gi"
    disk_size_gib: int = 81
    bootstrap_disk_size_gib: int = 1
    bootstrap_xml_template_secret_id: str = ""


@dataclass(frozen=True)
class GDCScenarioPodProfile:
    """Per-asset container image configuration for mixed scenario Pods."""

    image: str


@dataclass(frozen=True)
class GDCScenarioPodConfig:
    """Container image contract for pod-backed scenario assets on GDC."""

    image_pull_policy: str = "IfNotPresent"
    kali: GDCScenarioPodProfile = field(
        default_factory=lambda: GDCScenarioPodProfile("docker.io/kalilinux/kali-rolling:latest")
    )
    ubuntu: GDCScenarioPodProfile = field(
        default_factory=lambda: GDCScenarioPodProfile("docker.io/library/ubuntu:24.04")
    )

    def get_profile(self, *, os_type: str) -> GDCScenarioPodProfile:
        """Return the matching container image profile for a scenario pod."""
        if os_type == "kali":
            profile = self.kali
        elif os_type == "ubuntu":
            profile = self.ubuntu
        else:
            raise RuntimeError(f"scenario_pod assets only support kali or ubuntu, got {os_type!r}")

        if not profile.image:
            raise RuntimeError(
                f"Missing GDC scenario pod image for os_type={os_type!r}. "
                "Set the corresponding GDC_SCENARIO_POD_*_IMAGE environment variable."
            )
        return profile


@dataclass(frozen=True)
class NGFWAttachmentConfig:
    """Provider-neutral attachment and access contract for an NGFW instance."""

    cloud_provider: str
    management_ip: str = ""
    ssh_key_secret_ref: str = ""
    dataplane_ip: str = ""
    route_next_hop_ip: str = ""
    data_attachment_id: str = ""
    attachment_mode: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_attachable(self) -> bool:
        """Return True when the NGFW has the state needed for range attachment."""
        return bool(
            self.management_ip
            and self.ssh_key_secret_ref
            and (self.data_attachment_id or self.route_next_hop_ip or self.dataplane_ip)
        )


def _parse_csv_env(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _is_active_gdc_range_plane() -> bool:
    return os.environ.get("CLOUD_PROVIDER", "aws") == "gcp"


def _first_non_empty_string(*values: Any) -> str:
    """Return the first non-empty value as a normalized string."""
    for value in values:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
        elif value not in (None, ""):
            normalized = str(value).strip()
            if normalized:
                return normalized
    return ""


def _get_ngfw_provider_metadata(state: dict[str, Any], cloud_provider: str) -> dict[str, Any]:
    """Return the provider metadata block for an NGFW state payload."""
    provider_metadata = state.get("provider_metadata")
    if not isinstance(provider_metadata, dict):
        return {}

    if cloud_provider:
        metadata = provider_metadata.get(cloud_provider)
        if isinstance(metadata, dict):
            return metadata

    for provider_name in ("gcp", "gdc", "aws"):
        metadata = provider_metadata.get(provider_name)
        if isinstance(metadata, dict):
            return metadata

    return {}


def resolve_ngfw_attachment_config(state: dict[str, Any] | None) -> NGFWAttachmentConfig:
    """Resolve provider-neutral NGFW attachment details from stored state."""
    payload = state if isinstance(state, dict) else {}
    explicit_provider = _first_non_empty_string(payload.get("cloud_provider")).lower()
    cloud_provider = explicit_provider or os.environ.get("CLOUD_PROVIDER", "aws").lower()
    provider_metadata = _get_ngfw_provider_metadata(payload, cloud_provider)

    management_ip = _first_non_empty_string(
        payload.get("management_ip"),
        provider_metadata.get("management_ip"),
    )
    ssh_key_secret_ref = _first_non_empty_string(
        payload.get("ssh_key_secret_arn"),
        payload.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_key_secret_arn"),
        provider_metadata.get("ssh_key_secret_id"),
        provider_metadata.get("ssh_secret_ref"),
        provider_metadata.get("ssh_secret_id"),
    )
    dataplane_ip = _first_non_empty_string(
        payload.get("dataplane_ip"),
        provider_metadata.get("dataplane_ip"),
    )
    route_next_hop_ip = _first_non_empty_string(
        payload.get("route_next_hop_ip"),
        provider_metadata.get("route_next_hop_ip"),
        dataplane_ip,
    )
    data_attachment_id = _first_non_empty_string(
        payload.get("data_attachment_id"),
        payload.get("data_eni_id"),
        provider_metadata.get("data_attachment_id"),
        provider_metadata.get("data_eni_id"),
        provider_metadata.get("attachment_id"),
    )
    if not explicit_provider:
        if data_attachment_id:
            cloud_provider = "aws"
        elif route_next_hop_ip:
            cloud_provider = "gcp"
        provider_metadata = _get_ngfw_provider_metadata(payload, cloud_provider)
    attachment_mode = _first_non_empty_string(
        payload.get("attachment_mode"),
        provider_metadata.get("attachment_mode"),
        "aws-route-table-eni" if data_attachment_id else "",
        "gdc-static-route" if route_next_hop_ip else "",
    )

    return NGFWAttachmentConfig(
        cloud_provider=cloud_provider or "aws",
        management_ip=management_ip,
        ssh_key_secret_ref=ssh_key_secret_ref,
        dataplane_ip=dataplane_ip,
        route_next_hop_ip=route_next_hop_ip,
        data_attachment_id=data_attachment_id,
        attachment_mode=attachment_mode,
        provider_metadata=provider_metadata,
    )


def has_ngfw_attachment_state(state: dict[str, Any] | None) -> bool:
    """Return True when an NGFW state payload can attach to range networks."""
    return resolve_ngfw_attachment_config(state).is_attachable


def _get_int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def _load_gdc_vm_profile(
    prefix: str,
    *,
    default_vcpus: int,
    default_memory: str,
    default_disk_size_gib: int,
) -> GDCVMRuntimeProfile:
    """Load a role-specific VM Runtime sizing profile from env vars.

    The image URL is not read here; it is fetched at range-create time via
    ``main.get_gdc_image_url`` from Secret Manager.
    """
    return GDCVMRuntimeProfile(
        vcpus=_get_int_env(f"{prefix}_VCPUS", default_vcpus),
        memory=os.environ.get(f"{prefix}_MEMORY", default_memory).strip(),
        disk_size_gib=_get_int_env(f"{prefix}_DISK_SIZE_GIB", default_disk_size_gib),
    )


def _load_gdc_scenario_pod_profile(prefix: str, *, default_image: str) -> GDCScenarioPodProfile:
    """Load a role-specific scenario Pod profile from env vars."""
    return GDCScenarioPodProfile(
        image=os.environ.get(f"{prefix}_IMAGE", default_image).strip() or default_image,
    )


def _decode_gdc_access_secret(raw_secret: str) -> tuple[dict[str, Any], str]:
    payload: dict[str, Any] = {}
    kubeconfig = raw_secret
    try:
        parsed = json.loads(raw_secret)
    except json.JSONDecodeError:
        parsed = None

    if not isinstance(parsed, dict):
        return payload, kubeconfig

    payload = parsed
    kubeconfig = str(parsed.get("kubeconfig", "")).strip()
    if not kubeconfig:
        raise RuntimeError("GDC access secret is missing the kubeconfig field")
    return payload, kubeconfig


def _resolve_gdc_access_region(payload: dict[str, Any]) -> str:
    return str(
        payload.get("region")
        or os.environ.get("RANGE_NETWORK_REGION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("CLOUD_REGION")
        or os.environ.get("AWS_REGION", "")
    ).strip()


def _validate_gdc_access_fields(*, cluster_id: str, vxlan_cidr: str, region: str) -> None:
    if not cluster_id:
        raise RuntimeError("GDC access secret must include cluster_id or GDC_CLUSTER_ID must be set")
    if not vxlan_cidr:
        raise RuntimeError("GDC access secret must include vxlan_cidr or GDC_VXLAN_CIDR must be set")
    if not region:
        raise RuntimeError("GDC access secret must include region or RANGE_NETWORK_REGION/GCP_REGION must be set")


def load_gdc_network_access_config() -> GDCNetworkAccessConfig | None:
    """Load the GDC access bundle from Secret Manager when configured."""
    secret_id = os.environ.get("GDC_ACCESS_SECRET_ID", "").strip()
    if not secret_id:
        return None

    from cloud import get_secrets_store

    raw_secret = get_secrets_store().get_secret(secret_id)
    payload, kubeconfig = _decode_gdc_access_secret(raw_secret)
    cluster_id = str(payload.get("cluster_id") or os.environ.get("GDC_CLUSTER_ID", "")).strip()
    vxlan_cidr = str(payload.get("vxlan_cidr") or os.environ.get("GDC_VXLAN_CIDR", "")).strip()
    region = _resolve_gdc_access_region(payload)
    namespace_prefix = str(
        payload.get("range_namespace_prefix") or os.environ.get("GDC_RANGE_NAMESPACE_PREFIX", "range")
    )
    network_interface = str(payload.get("network_interface") or os.environ.get("GDC_NETWORK_INTERFACE", "vxlan0"))
    dns_nameservers = tuple(
        payload.get("dns_nameservers") or _parse_csv_env(os.environ.get("GDC_NETWORK_DNS_NAMESERVERS", "8.8.8.8"))
    )
    static_ip_reservation_count = int(
        payload.get("static_ip_reservation_count") or os.environ.get("GDC_STATIC_IP_RESERVATION_COUNT", "4")
    )
    _validate_gdc_access_fields(cluster_id=cluster_id, vxlan_cidr=vxlan_cidr, region=region)

    return GDCNetworkAccessConfig(
        access_secret_id=secret_id,
        kubeconfig=kubeconfig,
        cluster_id=cluster_id,
        vxlan_cidr=vxlan_cidr,
        region=region,
        namespace_prefix=namespace_prefix.strip() or "range",
        network_interface=network_interface.strip() or "vxlan0",
        dns_nameservers=dns_nameservers or ("8.8.8.8",),
        static_ip_reservation_count=static_ip_reservation_count,
    )


def load_gdc_vmruntime_config() -> GDCVMRuntimeConfig:
    """Load VM Runtime image and sizing configuration for GDC guest assets."""
    if not _is_active_gdc_range_plane():
        raise RuntimeError("GDC VM Runtime config is only valid when CLOUD_PROVIDER=gcp")

    return GDCVMRuntimeConfig(
        storage_class_name=os.environ.get("GDC_VM_STORAGE_CLASS", "local-shared").strip() or "local-shared",
        image_gcs_secret_id=os.environ.get("GDC_VM_IMAGE_GCS_SECRET_ID", "").strip(),
        kali=_load_gdc_vm_profile("GDC_KALI", default_vcpus=2, default_memory="4Gi", default_disk_size_gib=20),
        ubuntu=_load_gdc_vm_profile("GDC_UBUNTU", default_vcpus=1, default_memory="2Gi", default_disk_size_gib=20),
        windows=_load_gdc_vm_profile("GDC_WINDOWS", default_vcpus=2, default_memory="8Gi", default_disk_size_gib=64),
        dc=_load_gdc_vm_profile("GDC_DC", default_vcpus=2, default_memory="8Gi", default_disk_size_gib=64),
    )


def load_gdc_palo_alto_vmseries_config() -> GDCPaloAltoVMSeriesConfig:
    """Load Palo Alto VM-Series VM Runtime configuration for the GCP NGFW path."""
    if not _is_active_gdc_range_plane():
        raise RuntimeError("GDC Palo Alto VM-Series config is only valid when CLOUD_PROVIDER=gcp")

    bootstrap_bucket = os.environ.get("GDC_VMSERIES_BOOTSTRAP_BUCKET", "").strip()
    data_network_name = os.environ.get("GDC_VMSERIES_DATA_NETWORK_NAME", "").strip()
    route_next_hop_ip = os.environ.get("GDC_VMSERIES_ROUTE_NEXT_HOP_IP", "").strip()

    missing = [
        name
        for name, value in (
            ("GDC_VMSERIES_BOOTSTRAP_BUCKET", bootstrap_bucket),
            ("GDC_VMSERIES_DATA_NETWORK_NAME", data_network_name),
            ("GDC_VMSERIES_ROUTE_NEXT_HOP_IP", route_next_hop_ip),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing required GDC Palo Alto VM-Series configuration: " + ", ".join(missing))

    return GDCPaloAltoVMSeriesConfig(
        bootstrap_bucket=bootstrap_bucket,
        storage_class_name=os.environ.get("GDC_VMSERIES_STORAGE_CLASS", "").strip()
        or os.environ.get("GDC_VM_STORAGE_CLASS", "local-shared").strip()
        or "local-shared",
        image_gcs_secret_id=os.environ.get("GDC_VMSERIES_IMAGE_GCS_SECRET_ID", "").strip()
        or os.environ.get("GDC_VM_IMAGE_GCS_SECRET_ID", "").strip(),
        namespace_prefix=os.environ.get("GDC_VMSERIES_NAMESPACE_PREFIX", "ngfw").strip() or "ngfw",
        management_network_name=os.environ.get("GDC_VMSERIES_MGMT_NETWORK_NAME", "pod-network").strip()
        or "pod-network",
        management_ip_cidr=os.environ.get("GDC_VMSERIES_MGMT_IP_CIDR", "").strip(),
        data_network_name=data_network_name,
        data_ip_cidr=os.environ.get("GDC_VMSERIES_DATA_IP_CIDR", "").strip(),
        route_next_hop_ip=route_next_hop_ip,
        vcpus=_get_int_env("GDC_VMSERIES_VCPUS", 4),
        memory=os.environ.get("GDC_VMSERIES_MEMORY", "8Gi").strip() or "8Gi",
        disk_size_gib=_get_int_env("GDC_VMSERIES_DISK_SIZE_GIB", 81),
        bootstrap_disk_size_gib=_get_int_env("GDC_VMSERIES_BOOTSTRAP_DISK_SIZE_GIB", 1),
        bootstrap_xml_template_secret_id=os.environ.get(
            "GDC_VMSERIES_BOOTSTRAP_XML_TEMPLATE_SECRET_ID",
            "",
        ).strip(),
    )


def load_gdc_scenario_pod_config() -> GDCScenarioPodConfig:
    """Load image configuration for pod-backed scenario assets."""
    return GDCScenarioPodConfig(
        image_pull_policy=os.environ.get("GDC_SCENARIO_POD_IMAGE_PULL_POLICY", "IfNotPresent").strip()
        or "IfNotPresent",
        kali=_load_gdc_scenario_pod_profile(
            "GDC_SCENARIO_POD_KALI",
            default_image="docker.io/kalilinux/kali-rolling:latest",
        ),
        ubuntu=_load_gdc_scenario_pod_profile(
            "GDC_SCENARIO_POD_UBUNTU",
            default_image="docker.io/library/ubuntu:24.04",
        ),
    )


def load_range_network_config() -> RangeNetworkConfig:
    """Load the active provider's range-network contract from environment variables."""
    portal_network_cidrs = _parse_csv_env(os.environ.get("PORTAL_NETWORK_CIDRS", ""))
    legacy_portal_cidr = os.environ.get("PORTAL_VPC_CIDR", "")
    if not portal_network_cidrs and legacy_portal_cidr:
        portal_network_cidrs = (legacy_portal_cidr,)

    gdc_access = load_gdc_network_access_config() if _is_active_gdc_range_plane() else None
    if gdc_access is not None:
        return RangeNetworkConfig(
            network_id=gdc_access.cluster_id,
            network_cidr=gdc_access.vxlan_cidr,
            network_region=gdc_access.region,
            portal_network_cidrs=portal_network_cidrs,
        )

    return RangeNetworkConfig(
        network_id=os.environ.get("RANGE_NETWORK_ID") or os.environ.get("RANGE_VPC_ID", ""),
        network_cidr=os.environ.get("RANGE_NETWORK_CIDR") or os.environ.get("RANGE_VPC_CIDR", ""),
        network_region=(
            os.environ.get("RANGE_NETWORK_REGION")
            or os.environ.get("GCP_REGION")
            or os.environ.get("CLOUD_REGION")
            or os.environ.get("AWS_REGION", "")
        ),
        portal_network_cidrs=portal_network_cidrs,
    )


def get_range_availability_zone(default: str = "us-east-2b") -> str:
    """Return the configured range placement zone for AWS-style callers."""
    return (
        os.environ.get("RANGE_NETWORK_ZONE")
        or os.environ.get("RANGE_AVAILABILITY_ZONE")
        or os.environ.get("AVAILABILITY_ZONE")
        or default
    )


def get_range_from_db(range_id: int) -> dict[str, Any]:
    """Load range configuration from database.

    Returns range data with the new schema where range_config contains
    the full RangeSpec (scenario_id, user_id, subnets with instances).
    Also resolves provider-neutral NGFW attachment details from the user's
    active NGFW if the scenario has ngfw: true.

    Args:
        range_id: Database ID of the range.

    Returns:
        Dict with keys: id, user_id, request_uuid, range_config, ngfw_enabled,
        ngfw_data_eni_id, ngfw_instance_id, and ngfw_attachment.

    Raises:
        ValueError: If range not found.
    """
    logger.debug("Loading range %d from database", range_id)

    from main import get_db_connection

    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT
                    r.id,
                    r.user_id,
                    r.uuid,
                    r.range_config
                FROM mission_control_range r
                WHERE r.id = %s
                """,
            (range_id,),
        )
        row = cur.fetchone()
        if not row:
            logger.error("Range %d not found in database", range_id)
            raise ValueError(f"Range {range_id} not found")

        user_id = row[1]
        range_config = row[3] or {}

        # Check if scenario requires NGFW (ngfw: true in range_config)
        ngfw_enabled = range_config.get("ngfw", False)

        # Look up provider-neutral NGFW attachment data from the user's NGFW.
        ngfw_data_eni_id = ""
        ngfw_instance_id = None
        ngfw_attachment: dict[str, Any] = {}
        if ngfw_enabled:
            cur.execute(
                """
                SELECT ei.state, ei.id
                FROM engine_instance ei
                JOIN engine_request er ON ei.request_id = er.id
                WHERE er.user_id = %s
                  AND ei.role = 'ngfw'
                  AND ei.status IN ('ready', 'paused', 'pausing', 'resuming')
                ORDER BY ei.created_at DESC
                LIMIT 1
                """,
                (user_id,),
            )
            ngfw_row = cur.fetchone()
            if ngfw_row:
                resolved_attachment = resolve_ngfw_attachment_config(ngfw_row[0] or {})
                if resolved_attachment.is_attachable:
                    ngfw_data_eni_id = resolved_attachment.data_attachment_id
                    ngfw_instance_id = ngfw_row[1]
                    ngfw_attachment = {
                        "cloud_provider": resolved_attachment.cloud_provider,
                        "management_ip": resolved_attachment.management_ip,
                        "ssh_key_secret_ref": resolved_attachment.ssh_key_secret_ref,
                        "dataplane_ip": resolved_attachment.dataplane_ip,
                        "route_next_hop_ip": resolved_attachment.route_next_hop_ip,
                        "data_attachment_id": resolved_attachment.data_attachment_id,
                        "attachment_mode": resolved_attachment.attachment_mode,
                        "provider_metadata": resolved_attachment.provider_metadata,
                    }
                    logger.debug(
                        "Found NGFW attachment mode=%s instance_id=%s for user %d",
                        resolved_attachment.attachment_mode,
                        ngfw_instance_id,
                        user_id,
                    )

        result = {
            "id": row[0],
            "user_id": user_id,
            "request_uuid": str(row[2]) if row[2] else "",
            "range_config": range_config,
            "ngfw_enabled": ngfw_enabled,
            "ngfw_data_eni_id": ngfw_data_eni_id,
            "ngfw_instance_id": ngfw_instance_id,
            "ngfw_attachment": ngfw_attachment,
        }

        logger.debug(
            "Loaded range %d: ngfw_enabled=%s, ngfw_attachment=%s",
            range_id,
            result["ngfw_enabled"],
            "present" if result["ngfw_attachment"] else "none",
        )

        return result
