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

from log_redact import safe_log_fingerprint

logger = logging.getLogger(__name__)


class FieldDecryptError(RuntimeError):
    """Raised when an encrypted field cannot be decrypted.

    Fail-closed (#1189): the provisioner refuses to continue with
    ciphertext or malformed values silently. Callers that catch this
    error must decide explicitly whether to abort the request or fall
    back to a documented test/local plaintext mode — the function
    itself never returns the raw input on failure.
    """


def decrypt_field(encrypted_value: str) -> str:
    """Decrypt a Fernet-encrypted field value.

    Used for sensitive fields that are encrypted at rest in the Django
    database using django-encrypted-model-fields. Fail-closed: any
    decryption failure raises ``FieldDecryptError`` rather than
    silently returning the input. Exception messages never include
    the input value.

    Args:
        encrypted_value: Base64-url-encoded Fernet ciphertext.

    Returns:
        Decrypted plaintext string. Empty input returns ``""`` as the
        "no field present" sentinel.

    Raises:
        FieldDecryptError: ``FIELD_ENCRYPTION_KEY`` is missing for a
            non-empty input; input is not valid base64-url; the Fernet
            token is malformed; the key is wrong; or any other decrypt
            failure.
    """
    if not encrypted_value:
        return ""

    key = os.environ.get("FIELD_ENCRYPTION_KEY")
    if not key:
        # Drift signal: caller supplied an encrypted-looking value but
        # the encryption key isn't configured. The previous behavior
        # (pass-through) hid mis-configured secret flows; refuse instead.
        raise FieldDecryptError("FIELD_ENCRYPTION_KEY is not set; cannot decrypt provisioner field")

    try:
        fernet = Fernet(key.encode() if isinstance(key, str) else key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode("ascii"))
        return fernet.decrypt(encrypted_bytes).decode("utf-8")
    except Exception as e:
        # Wrap the underlying cryptography / binascii error so callers
        # see one stable exception type. The original exception is
        # chained for diagnostic logs, but the message we surface here
        # never carries the input value.
        logger.warning("Failed to decrypt provisioner field (%s)", type(e).__name__)
        raise FieldDecryptError("failed to decrypt provisioner field") from e


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
    """Per-guest VM Runtime image and sizing configuration."""

    source_url: str = ""
    vcpus: int = 1
    memory: str = "2Gi"
    disk_size_gib: int = 20


@dataclass(frozen=True)
class GDCVMRuntimeConfig:
    """VM Runtime image and sizing contract for the active GCP range plane."""

    storage_class_name: str = "local-shared"
    image_gcs_secret_id: str = ""
    kali: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)
    ubuntu: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)
    windows: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)
    dc: GDCVMRuntimeProfile = field(default_factory=GDCVMRuntimeProfile)

    def get_profile(self, *, role: str, os_type: str) -> GDCVMRuntimeProfile:
        """Return the matching VM Runtime profile for a scenario instance."""
        if role == "dc":
            profile = self.dc
        elif os_type == "kali":
            profile = self.kali
        elif os_type == "windows":
            profile = self.windows
        else:
            profile = self.ubuntu

        if not profile.source_url:
            raise RuntimeError(
                f"Missing GDC VM Runtime image URL for role={role!r} os_type={os_type!r}. "
                "Set the corresponding GDC_*_IMAGE_URL environment variable."
            )
        return profile


@dataclass(frozen=True)
class GDCPaloAltoVMSeriesConfig:
    """Palo Alto VM-Series VM Runtime contract for the active GCP NGFW path."""

    image_url: str
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
class GCERangeImageProfile:
    """Image and sizing contract for one Compute Engine range guest family."""

    source_image: str = ""
    machine_type: str = "e2-medium"
    disk_size_gb: int = 30
    disk_type: str = "pd-balanced"


@dataclass(frozen=True)
class GCERangeCellConfig:
    """Configuration for the GCE-backed live-fire range-cell backend."""

    project_id: str
    region: str
    zone: str
    network_mode: str
    # Self-link (or partial URL ``projects/<p>/global/networks/<name>``) of the
    # shared range VPC used in ``shared-vpc`` mode. Range subnets are created in
    # this pre-existing, platform-peered VPC (matching the AWS shared-VPC +
    # per-range-subnet model) so the provisioner can reach guests. Empty in
    # ``vpc-per-range`` mode, where each range mints its own VPC.
    network_id: str = ""
    service_account_email: str = ""
    # OAuth scope for the range guest's attached service account. Use
    # cloud-platform and let the host SA's IAM roles be the real access control
    # (the modern GCP recommendation): scopes are a coarse legacy gate, IAM is
    # fine-grained. cloud-platform is REQUIRED, not merely convenient — the
    # Polaris range host must read Cloud Storage (the smoketest tarball) and
    # Secret Manager (its per-range Vertex key), and Secret Manager has no
    # narrower OAuth scope than cloud-platform, so narrow logging/monitoring
    # scopes made both fail with a generic 403 regardless of IAM. The blast
    # radius stays bounded by the host SA's minimal roles, and the
    # participant-facing container is blocked from the metadata server so it can
    # never read this token (see gcp_range_cell_resources + the Vertex shard).
    service_account_scopes: tuple[str, ...] = ("https://www.googleapis.com/auth/cloud-platform",)
    linux: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    kali: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    windows: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    dc: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    portal_network_cidrs: tuple[str, ...] = ()
    egress_allow_cidrs: tuple[str, ...] = ()
    # Pre-provisioned Vertex-only service account. When set, the range-cell
    # backend mints a per-range key on this SA (created and destroyed with the
    # range), stores it by reference in Secret Manager, and the range bootstrap
    # injects it into the participant agent container. This keeps the agent's
    # cloud credential scoped to Vertex and per-range revocable, and the
    # container is blocked from the metadata server so it can never mint the
    # broader range-host SA token. Empty disables per-range agent credentials.
    vertex_service_account_email: str = ""
    # Private Google Access on the range subnet lets no-external-IP guests reach
    # Google APIs (Vertex AI for the Polaris agent, GCS for the smoketest
    # tarball, Secret Manager for the per-range Vertex key) over internal
    # routing. When set, ``_firewall_plan`` automatically emits the matching
    # egress-allow to the private.googleapis.com VIP (no need to hand-list it in
    # ``egress_allow_cidrs``); the range VPC supplies the DNS zone + route. Off
    # by default for maximum isolation.
    private_google_access: bool = False
    # Management SSH port for Docker-host range guests (e.g. the Polaris range
    # host) whose participant container publishes host :22, forcing the host
    # sshd the provisioner drives to a dedicated port. Native single-service
    # guests keep :22.
    host_mgmt_ssh_port: int = 2222
    metadata_items: tuple[tuple[str, str], ...] = (
        ("block-project-ssh-keys", "true"),
        ("enable-oslogin", "false"),
        ("serial-port-enable", "false"),
    )

    def get_profile(self, *, role: str, os_type: str, requested_type: str = "") -> GCERangeImageProfile:
        """Return the image profile for a range guest, applying instance-type overrides."""
        if role == "dc":
            profile = self.dc
        elif os_type == "kali" or role == "attacker":
            profile = self.kali if self.kali.source_image else self.linux
        elif os_type == "windows":
            profile = self.windows
        else:
            profile = self.linux

        if not profile.source_image:
            raise RuntimeError(
                f"Missing GCE range image for role={role!r} os_type={os_type!r}. "
                "Set the corresponding GCP_RANGE_*_IMAGE environment variable."
            )
        if requested_type:
            return GCERangeImageProfile(
                source_image=profile.source_image,
                machine_type=requested_type,
                disk_size_gb=profile.disk_size_gb,
                disk_type=profile.disk_type,
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


def get_gcp_range_backend() -> str:
    """Return the selected GCP range backend.

    GCE range cells are the default GCP path, so ``gce`` is assumed whenever
    ``CLOUD_PROVIDER=gcp`` and no explicit backend is configured. The historical
    GDC VM Runtime path remains fully supported and is selected explicitly with
    ``GCP_RANGE_BACKEND=gdc`` (a one-line rollback for any environment).
    """
    if os.environ.get("CLOUD_PROVIDER", "aws") != "gcp":
        return ""
    backend = os.environ.get("GCP_RANGE_BACKEND") or os.environ.get("GCP_RANGE_PLANE") or "gce"
    backend = backend.strip().lower()
    if backend not in {"gdc", "gce"}:
        raise RuntimeError(f"GCP_RANGE_BACKEND must be 'gdc' or 'gce', got {backend!r}")
    return backend


def _is_active_gdc_range_plane() -> bool:
    return get_gcp_range_backend() == "gdc"


def is_gce_range_cell_backend() -> bool:
    """Return True when GCP ranges should be provisioned as GCE range cells."""
    return get_gcp_range_backend() == "gce"


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


def _infer_ngfw_cloud_provider(data_attachment_id: str, route_next_hop_ip: str, env_default: str) -> str:
    """Infer the cloud provider when state omits an explicit ``cloud_provider``.

    GCP data attachments are namespaced KubeVirt references such as
    ``"<namespace>/<vm>:eth1"``; AWS ENI ids (``"eni-..."``) never contain a
    ``"/"`` or ``":"``. Inferring AWS from any ``data_attachment_id`` would
    misclassify a GCP NGFW whose explicit ``cloud_provider`` was dropped.
    """
    if data_attachment_id:
        return "gcp" if ("/" in data_attachment_id or ":" in data_attachment_id) else "aws"
    if route_next_hop_ip:
        return "gcp"
    return env_default


def _resolve_ngfw_attachment_mode(
    payload: dict[str, Any],
    provider_metadata: dict[str, Any],
    cloud_provider: str,
    data_attachment_id: str,
    route_next_hop_ip: str,
) -> str:
    """Resolve the attachment mode, falling back to a provider-appropriate default."""
    default_mode = ""
    if cloud_provider == "gcp" and (route_next_hop_ip or data_attachment_id):
        default_mode = "gdc-static-route"
    elif cloud_provider == "aws" and data_attachment_id:
        default_mode = "aws-route-table-eni"
    return _first_non_empty_string(
        payload.get("attachment_mode"),
        provider_metadata.get("attachment_mode"),
        default_mode,
    )


def resolve_ngfw_attachment_config(state: dict[str, Any] | None) -> NGFWAttachmentConfig:
    """Resolve provider-neutral NGFW attachment details from stored state."""
    payload = state if isinstance(state, dict) else {}
    explicit_provider = _first_non_empty_string(payload.get("cloud_provider")).lower()
    env_default = os.environ.get("CLOUD_PROVIDER", "aws").lower()
    cloud_provider = explicit_provider or env_default
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
        cloud_provider = _infer_ngfw_cloud_provider(data_attachment_id, route_next_hop_ip, env_default)
        provider_metadata = _get_ngfw_provider_metadata(payload, cloud_provider)
    attachment_mode = _resolve_ngfw_attachment_mode(
        payload, provider_metadata, cloud_provider, data_attachment_id, route_next_hop_ip
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


def _get_bool_env(name: str, default: bool) -> bool:
    """Return a boolean env var, treating 1/true/yes/on as true."""
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def _load_gdc_vm_profile(
    prefix: str,
    *,
    default_vcpus: int,
    default_memory: str,
    default_disk_size_gib: int,
) -> GDCVMRuntimeProfile:
    """Load a role-specific VM Runtime profile from env vars."""
    return GDCVMRuntimeProfile(
        source_url=os.environ.get(f"{prefix}_IMAGE_URL", "").strip(),
        vcpus=_get_int_env(f"{prefix}_VCPUS", default_vcpus),
        memory=os.environ.get(f"{prefix}_MEMORY", default_memory).strip(),
        disk_size_gib=_get_int_env(f"{prefix}_DISK_SIZE_GIB", default_disk_size_gib),
    )


def _load_gdc_scenario_pod_profile(prefix: str, *, default_image: str) -> GDCScenarioPodProfile:
    """Load a role-specific scenario Pod profile from env vars."""
    return GDCScenarioPodProfile(
        image=os.environ.get(f"{prefix}_IMAGE", default_image).strip() or default_image,
    )


def _load_gce_range_profile(
    prefix: str,
    *,
    default_machine_type: str,
    default_disk_size_gb: int,
) -> GCERangeImageProfile:
    """Load one GCE range guest image/sizing profile."""
    return GCERangeImageProfile(
        source_image=os.environ.get(f"{prefix}_IMAGE", "").strip(),
        machine_type=os.environ.get(f"{prefix}_MACHINE_TYPE", default_machine_type).strip() or default_machine_type,
        disk_size_gb=_get_int_env(f"{prefix}_DISK_SIZE_GB", default_disk_size_gb),
        disk_type=os.environ.get(f"{prefix}_DISK_TYPE", "pd-balanced").strip() or "pd-balanced",
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


def _resolve_gdc_network_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve GDC network-access fields from the secret payload with env fallbacks."""
    return {
        "cluster_id": str(payload.get("cluster_id") or os.environ.get("GDC_CLUSTER_ID", "")).strip(),
        "vxlan_cidr": str(payload.get("vxlan_cidr") or os.environ.get("GDC_VXLAN_CIDR", "")).strip(),
        "region": _resolve_gdc_access_region(payload),
        "namespace_prefix": str(
            payload.get("range_namespace_prefix") or os.environ.get("GDC_RANGE_NAMESPACE_PREFIX", "range")
        ),
        "network_interface": str(payload.get("network_interface") or os.environ.get("GDC_NETWORK_INTERFACE", "vxlan0")),
        "dns_nameservers": tuple(
            payload.get("dns_nameservers") or _parse_csv_env(os.environ.get("GDC_NETWORK_DNS_NAMESERVERS", ""))
        ),
        "static_ip_reservation_count": int(
            payload.get("static_ip_reservation_count") or os.environ.get("GDC_STATIC_IP_RESERVATION_COUNT", "4")
        ),
    }


def load_gdc_network_access_config() -> GDCNetworkAccessConfig | None:
    """Load the GDC access bundle from Secret Manager when configured."""
    secret_id = os.environ.get("GDC_ACCESS_SECRET_ID", "").strip()
    if not secret_id:
        return None

    from cloud import get_secrets_store

    raw_secret = get_secrets_store().get_secret(secret_id)
    payload, kubeconfig = _decode_gdc_access_secret(raw_secret)
    fields = _resolve_gdc_network_fields(payload)
    _validate_gdc_access_fields(
        cluster_id=fields["cluster_id"], vxlan_cidr=fields["vxlan_cidr"], region=fields["region"]
    )

    config_kwargs: dict[str, Any] = {
        "access_secret_id": secret_id,
        "kubeconfig": kubeconfig,
        "cluster_id": fields["cluster_id"],
        "vxlan_cidr": fields["vxlan_cidr"],
        "region": fields["region"],
        "namespace_prefix": fields["namespace_prefix"].strip() or "range",
        "network_interface": fields["network_interface"].strip() or "vxlan0",
        "static_ip_reservation_count": fields["static_ip_reservation_count"],
    }
    # Only override the dataclass default ("8.8.8.8",) when nameservers were resolved.
    if fields["dns_nameservers"]:
        config_kwargs["dns_nameservers"] = fields["dns_nameservers"]
    return GDCNetworkAccessConfig(**config_kwargs)


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


def _require_vmseries_env(
    *, image_url: str, bootstrap_bucket: str, data_network_name: str, route_next_hop_ip: str
) -> None:
    """Raise if any required VM-Series env var is empty."""
    missing = [
        name
        for name, value in (
            ("GDC_VMSERIES_IMAGE_URL", image_url),
            ("GDC_VMSERIES_BOOTSTRAP_BUCKET", bootstrap_bucket),
            ("GDC_VMSERIES_DATA_NETWORK_NAME", data_network_name),
            ("GDC_VMSERIES_ROUTE_NEXT_HOP_IP", route_next_hop_ip),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing required GDC Palo Alto VM-Series configuration: " + ", ".join(missing))


def _resolve_vmseries_storage_and_secret() -> tuple[str, str]:
    """Resolve VM-Series storage class and image secret with VM-runtime fallbacks."""
    storage_class_name = (
        os.environ.get("GDC_VMSERIES_STORAGE_CLASS", "").strip()
        or os.environ.get("GDC_VM_STORAGE_CLASS", "local-shared").strip()
        or "local-shared"
    )
    image_gcs_secret_id = (
        os.environ.get("GDC_VMSERIES_IMAGE_GCS_SECRET_ID", "").strip()
        or os.environ.get("GDC_VM_IMAGE_GCS_SECRET_ID", "").strip()
    )
    return storage_class_name, image_gcs_secret_id


def load_gdc_palo_alto_vmseries_config() -> GDCPaloAltoVMSeriesConfig:
    """Load Palo Alto VM-Series VM Runtime configuration for the GCP NGFW path."""
    if not _is_active_gdc_range_plane():
        raise RuntimeError("GDC Palo Alto VM-Series config is only valid when CLOUD_PROVIDER=gcp")

    image_url = os.environ.get("GDC_VMSERIES_IMAGE_URL", "").strip()
    bootstrap_bucket = os.environ.get("GDC_VMSERIES_BOOTSTRAP_BUCKET", "").strip()
    data_network_name = os.environ.get("GDC_VMSERIES_DATA_NETWORK_NAME", "").strip()
    route_next_hop_ip = os.environ.get("GDC_VMSERIES_ROUTE_NEXT_HOP_IP", "").strip()

    _require_vmseries_env(
        image_url=image_url,
        bootstrap_bucket=bootstrap_bucket,
        data_network_name=data_network_name,
        route_next_hop_ip=route_next_hop_ip,
    )
    storage_class_name, image_gcs_secret_id = _resolve_vmseries_storage_and_secret()

    return GDCPaloAltoVMSeriesConfig(
        image_url=image_url,
        bootstrap_bucket=bootstrap_bucket,
        storage_class_name=storage_class_name,
        image_gcs_secret_id=image_gcs_secret_id,
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


def _resolve_gce_range_required_env() -> tuple[str, str, str, str]:
    """Resolve required environment for the GCE range-cell backend.

    ``GCP_RANGE_CELL_PROJECT_ID`` takes precedence so range cells can be
    provisioned into a different project than the control plane's
    ``GCP_PROJECT_ID`` (and so the range backend is unaffected when the
    control-plane project is a deploy-overlay placeholder). It falls back to the
    control-plane project keys, mirroring ``GCP_RANGE_VERTEX_PROJECT_ID``.
    """
    project_id = (
        os.environ.get("GCP_RANGE_CELL_PROJECT_ID")
        or os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUD_PROJECT_ID")
        or ""
    ).strip()
    region = (
        os.environ.get("RANGE_NETWORK_REGION") or os.environ.get("GCP_REGION") or os.environ.get("CLOUD_REGION") or ""
    ).strip()
    zone = get_range_availability_zone(default="").strip()
    service_account_email = os.environ.get("GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL", "").strip()
    return project_id, region, zone, service_account_email


def _missing_gce_range_required_env(
    *,
    project_id: str,
    region: str,
    zone: str,
    service_account_email: str,
) -> list[str]:
    """Return display names for missing GCE range-cell settings."""
    return [
        name
        for name, value in (
            ("GCP_RANGE_CELL_PROJECT_ID/GCP_PROJECT_ID", project_id),
            ("RANGE_NETWORK_REGION/GCP_REGION", region),
            ("RANGE_NETWORK_ZONE", zone),
            ("GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL", service_account_email),
        )
        if not value
    ]


def load_gce_range_cell_config() -> GCERangeCellConfig:
    """Load the live-fire GCE range-cell backend configuration."""
    if not is_gce_range_cell_backend():
        raise RuntimeError("GCE range-cell config is only valid when CLOUD_PROVIDER=gcp and GCP_RANGE_BACKEND=gce")

    project_id, region, zone, service_account_email = _resolve_gce_range_required_env()
    missing = _missing_gce_range_required_env(
        project_id=project_id,
        region=region,
        zone=zone,
        service_account_email=service_account_email,
    )
    if missing:
        raise RuntimeError("Missing required GCE range-cell configuration: " + ", ".join(missing))

    # Default: shared-vpc. Range subnets live in the pre-existing, platform-peered
    # range VPC (RANGE_NETWORK_ID/RANGE_VPC_ID) so the provisioner can reach guests,
    # matching the AWS shared-VPC + per-range-subnet model. vpc-per-range mints an
    # isolated VPC per range; it currently has no provisioner reachability path
    # (no peering/IAP), so it is selectable but not the default.
    network_mode = os.environ.get("GCP_RANGE_CELL_NETWORK_MODE", "shared-vpc").strip().lower()
    if network_mode not in ("shared-vpc", "vpc-per-range"):
        raise RuntimeError("GCP_RANGE_CELL_NETWORK_MODE must be 'shared-vpc' or 'vpc-per-range'")

    network_id = (os.environ.get("RANGE_NETWORK_ID") or os.environ.get("RANGE_VPC_ID", "")).strip()
    if network_mode == "shared-vpc" and not network_id:
        raise RuntimeError("shared-vpc range networking requires RANGE_NETWORK_ID or RANGE_VPC_ID")

    return GCERangeCellConfig(
        project_id=project_id,
        region=region,
        zone=zone,
        network_mode=network_mode,
        network_id=network_id,
        service_account_email=service_account_email,
        # cloud-platform, not narrow logging/monitoring: the range host must read
        # Cloud Storage (smoketest tarball) and Secret Manager (per-range Vertex
        # key), and Secret Manager has no narrower OAuth scope. IAM on the host SA
        # is the real access control; the participant container is metadata-blocked
        # so it can never read this token. See the service_account_scopes field.
        service_account_scopes=_parse_csv_env(
            os.environ.get(
                "GCP_RANGE_HOST_SERVICE_ACCOUNT_SCOPES",
                "https://www.googleapis.com/auth/cloud-platform",
            )
        ),
        linux=_load_gce_range_profile(
            "GCP_RANGE_LINUX",
            default_machine_type="e2-standard-2",
            default_disk_size_gb=50,
        ),
        kali=_load_gce_range_profile(
            "GCP_RANGE_KALI",
            default_machine_type="e2-standard-4",
            default_disk_size_gb=80,
        ),
        windows=_load_gce_range_profile(
            "GCP_RANGE_WINDOWS",
            default_machine_type="e2-standard-4",
            # The shifter-windows image is a 100 GB disk; a boot disk cannot be
            # smaller than its source image, so the default must be >= 100 or
            # every Windows guest fails at create. Override via
            # GCP_RANGE_WINDOWS_DISK_SIZE_GB for a larger image.
            default_disk_size_gb=100,
        ),
        dc=_load_gce_range_profile(
            "GCP_RANGE_DC",
            default_machine_type="e2-standard-4",
            default_disk_size_gb=100,
        ),
        portal_network_cidrs=_parse_csv_env(
            os.environ.get("PORTAL_NETWORK_CIDRS", "") or os.environ.get("PORTAL_VPC_CIDR", "")
        ),
        egress_allow_cidrs=_parse_csv_env(os.environ.get("GCP_RANGE_EGRESS_ALLOW_CIDRS", "")),
        vertex_service_account_email=os.environ.get("GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL", "").strip(),
        private_google_access=_get_bool_env("GCP_RANGE_PRIVATE_GOOGLE_ACCESS", False),
        host_mgmt_ssh_port=_get_int_env("GCP_RANGE_HOST_MGMT_SSH_PORT", 2222),
    )


def _load_portal_network_cidrs() -> tuple[str, ...]:
    """Load portal CIDRs with the legacy single-CIDR fallback."""
    portal_network_cidrs = _parse_csv_env(os.environ.get("PORTAL_NETWORK_CIDRS", ""))
    legacy_portal_cidr = os.environ.get("PORTAL_VPC_CIDR", "")
    if not portal_network_cidrs and legacy_portal_cidr:
        return (legacy_portal_cidr,)
    return portal_network_cidrs


def _resolve_range_project_id() -> str:
    """Resolve the active cloud project id used by range networking."""
    return (
        os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("CLOUD_PROJECT_ID")
        or ""
    ).strip()


def _resolve_range_network_region() -> str:
    """Resolve the range network region from current provider env."""
    return (
        os.environ.get("RANGE_NETWORK_REGION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("CLOUD_REGION")
        or os.environ.get("AWS_REGION", "")
    )


def _default_range_network_id(project_id: str) -> str:
    """Return the provider-specific default range network id."""
    if is_gce_range_cell_backend():
        return f"gcp-range-cells:{project_id}"
    return ""


def load_range_network_config() -> RangeNetworkConfig:
    """Load the active provider's range-network contract from environment variables."""
    portal_network_cidrs = _load_portal_network_cidrs()
    gdc_access = load_gdc_network_access_config() if _is_active_gdc_range_plane() else None
    if gdc_access is not None:
        return RangeNetworkConfig(
            network_id=gdc_access.cluster_id,
            network_cidr=gdc_access.vxlan_cidr,
            network_region=gdc_access.region,
            portal_network_cidrs=portal_network_cidrs,
        )

    project_id = _resolve_range_project_id()
    return RangeNetworkConfig(
        network_id=os.environ.get("RANGE_NETWORK_ID")
        or os.environ.get("RANGE_VPC_ID", "")
        or _default_range_network_id(project_id),
        network_cidr=os.environ.get("RANGE_NETWORK_CIDR") or os.environ.get("RANGE_VPC_CIDR", ""),
        network_region=_resolve_range_network_region(),
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

    from provisioner_db import get_db_connection

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
        from cyberscript.persisted_envelope import unwrap_persisted_spec

        range_config = unwrap_persisted_spec(row[3] or {})

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
            "Loaded range range_fp=%s: ngfw_enabled=%s, ngfw_attachment=%s",
            safe_log_fingerprint(range_id),
            result["ngfw_enabled"],
            "present" if result["ngfw_attachment"] else "none",
        )

        return result
