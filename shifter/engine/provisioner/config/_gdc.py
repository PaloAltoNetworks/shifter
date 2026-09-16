"""GDC (Google Distributed Cloud) VM Runtime and scenario-Pod configuration.

Depends on the ``_env`` leaf, the ``_gcp_backend`` leaf (for
``_is_active_gdc_range_plane``), and the dependency-light ``shared.sftp_root``
validator/defaults (for the per-image SFTP root).
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any

from shared.sftp_root import DEFAULT_SFTP_ROOT_BY_OS, SftpRootError, normalize_sftp_root_directory

from ._env import _get_int_env, _parse_csv_env
from ._gcp_backend import _is_active_gdc_range_plane


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
    # NOSONAR - public DNS resolver default (Google Public DNS), not a sensitive/internal address
    dns_nameservers: tuple[str, ...] = ("8.8.8.8",)  # NOSONAR
    static_ip_reservation_count: int = 4


@dataclass(frozen=True)
class GDCVMRuntimeProfile:
    """Per-guest VM Runtime image and sizing configuration."""

    source_url: str = ""
    vcpus: int = 1
    memory: str = "2Gi"
    disk_size_gib: int = 20
    # Non-secret guest-visible Guacamole SFTP root for this image (#375). Declared
    # per image so two images of the same os_type can pin different roots; the
    # built-in values are seeded as defaults in ``load_gdc_vmruntime_config``.
    sftp_root_directory: str = ""


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


def _load_gdc_vm_profile(
    prefix: str,
    *,
    default_vcpus: int,
    default_memory: str,
    default_disk_size_gib: int,
    default_sftp_root_directory: str = "",
) -> GDCVMRuntimeProfile:
    """Load a role-specific VM Runtime profile from env vars."""
    sftp_root_directory = os.environ.get(f"{prefix}_SFTP_ROOT_DIRECTORY", default_sftp_root_directory).strip()
    if sftp_root_directory:
        try:
            normalize_sftp_root_directory(sftp_root_directory)
        except SftpRootError as exc:
            raise RuntimeError(f"{prefix}_SFTP_ROOT_DIRECTORY is invalid: {exc}") from exc
    return GDCVMRuntimeProfile(
        source_url=os.environ.get(f"{prefix}_IMAGE_URL", "").strip(),
        vcpus=_get_int_env(f"{prefix}_VCPUS", default_vcpus),
        memory=os.environ.get(f"{prefix}_MEMORY", default_memory).strip(),
        disk_size_gib=_get_int_env(f"{prefix}_DISK_SIZE_GIB", default_disk_size_gib),
        sftp_root_directory=sftp_root_directory,
    )


def _load_gdc_scenario_pod_profile(prefix: str, *, default_image: str) -> GDCScenarioPodProfile:
    """Load a role-specific scenario Pod profile from env vars."""
    return GDCScenarioPodProfile(
        image=os.environ.get(f"{prefix}_IMAGE", default_image).strip() or default_image,
    )


def _decode_gdc_access_secret(raw_secret: str) -> tuple[dict[str, Any], str]:
    """Decode the GDC access secret, returning its JSON payload and kubeconfig."""
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
    """Resolve the GDC access region from the secret payload or region env vars."""
    return str(
        payload.get("region")
        or os.environ.get("RANGE_NETWORK_REGION")
        or os.environ.get("GCP_REGION")
        or os.environ.get("CLOUD_REGION")
        or os.environ.get("AWS_REGION", "")
    ).strip()


def _validate_gdc_access_fields(*, cluster_id: str, vxlan_cidr: str, region: str) -> None:
    """Raise ``RuntimeError`` if any required GDC access field is missing."""
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
        kali=_load_gdc_vm_profile(
            "GDC_KALI",
            default_vcpus=2,
            default_memory="4Gi",
            default_disk_size_gib=20,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["kali"],
        ),
        ubuntu=_load_gdc_vm_profile(
            "GDC_UBUNTU",
            default_vcpus=1,
            default_memory="2Gi",
            default_disk_size_gib=20,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["ubuntu"],
        ),
        windows=_load_gdc_vm_profile(
            "GDC_WINDOWS",
            default_vcpus=2,
            default_memory="8Gi",
            default_disk_size_gib=64,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["windows"],
        ),
        dc=_load_gdc_vm_profile(
            "GDC_DC",
            default_vcpus=2,
            default_memory="8Gi",
            default_disk_size_gib=64,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["windows"],
        ),
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
