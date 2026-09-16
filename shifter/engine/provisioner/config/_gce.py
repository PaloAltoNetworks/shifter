"""GCE (Compute Engine) live-fire range-cell backend configuration.

Depends on the ``_env`` leaf, the ``_gcp_backend`` leaf, ``_range`` (for
``get_range_availability_zone``), the dependency-light ``shared.sftp_root``
defaults (for the per-class SFTP root seed), and its own ``_gce_profile`` /
``_gce_image_keys`` leaves. The guest image profile contract and its validation
live in ``_gce_profile``; the keyed image-profile map parser lives in
``_gce_image_keys``. Both are re-exported here so the module's public surface is
unchanged.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from shared.sftp_root import DEFAULT_SFTP_ROOT_BY_OS

from ._env import _get_bool_env, _get_int_env, _parse_csv_env
from ._gce_image_keys import _load_gce_image_key_profiles
from ._gce_profile import (
    _GCE_LOGICAL_NAME_RE,
    GCE_BOOTSTRAP_POLARIS_HOST,
    GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
    GCE_BOOTSTRAP_PREPROMOTED_DC,
    GCE_BOOTSTRAP_STANDARD,
    GCE_PARTICIPANT_READINESS_CONTRACT_V1,
    GCE_SUPPORTED_BOOTSTRAP_CAPABILITIES,
    GCERangeImageProfile,
    _load_gce_range_profile,
    _profile_has_source,
    gce_image_profile_fingerprint,
)
from ._gce_required import missing_gce_range_required_env, resolve_gce_range_required_env
from ._gcp_backend import is_gce_range_cell_backend

__all__ = [
    "GCE_BOOTSTRAP_POLARIS_HOST",
    "GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST",
    "GCE_BOOTSTRAP_PREPROMOTED_DC",
    "GCE_BOOTSTRAP_STANDARD",
    "GCE_PARTICIPANT_READINESS_CONTRACT_V1",
    "GCE_SUPPORTED_BOOTSTRAP_CAPABILITIES",
    "GCERangeCellConfig",
    "GCERangeImageProfile",
    "gce_image_profile_fingerprint",
    "load_gce_range_cell_config",
]


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
    model_broker_vip: str = ""
    service_account_email: str = ""
    # OAuth scope for a range host's attached service account. Use
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
    # Number of pre-created, no-role range-host service accounts available to
    # exact machine-image profiles. A range's existing subnet allocation slot
    # selects one identity deterministically; zero disables the capability.
    range_host_identity_pool_size: int = 0
    linux: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    kali: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    windows: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    dc: GCERangeImageProfile = field(default_factory=GCERangeImageProfile)
    image_key_profiles: Mapping[str, Mapping[str, GCERangeImageProfile]] = field(default_factory=dict)
    portal_network_cidrs: tuple[str, ...] = ()
    # Dedicated participant/operator access-workload source ranges (portal + guacd
    # pods) that dial range guests for browser SSH and Guacamole SSH/RDP (issue
    # #1349). When set, the per-range participant ingress (22/3389) is sourced
    # from these ranges only -- distinct from provisioner/host management ingress,
    # which stays on ``portal_network_cidrs``. Empty falls back to
    # ``portal_network_cidrs`` so deployments without a dedicated access node pool
    # keep their current behavior.
    access_network_cidrs: tuple[str, ...] = ()
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

    def get_profile(
        self,
        *,
        role: str,
        os_type: str,
        requested_type: str = "",
        ami_key: str = "",
    ) -> GCERangeImageProfile:
        """Return the exact platform-approved image profile for a range guest."""
        if role == "dc":
            profile_class = "dc"
            profile = self.dc
        elif os_type == "kali" or role == "attacker":
            profile_class = "kali"
            profile = self.kali if _profile_has_source(self.kali) else self.linux
        elif os_type == "windows":
            profile_class = "windows"
            profile = self.windows
        else:
            profile_class = "linux"
            profile = self.linux

        logical_key = ami_key.strip()
        if logical_key:
            if not _GCE_LOGICAL_NAME_RE.fullmatch(logical_key):
                raise RuntimeError("GCE ami_key must be a lowercase logical key using letters, digits, and hyphens")
            mapped_profile = self.image_key_profiles.get(profile_class, {}).get(logical_key)
            if mapped_profile is None:
                raise RuntimeError(
                    "There is no configured GCE image profile for "
                    f"profile_class={profile_class!r} ami_key={logical_key!r}; "
                    "set GCP_RANGE_IMAGE_KEY_PROFILES_JSON before launching this scenario."
                )
            profile = mapped_profile

        if not _profile_has_source(profile):
            raise RuntimeError(
                f"Missing GCE range image for role={role!r} os_type={os_type!r}. "
                "Set the corresponding GCP_RANGE_*_IMAGE environment variable."
            )
        if requested_type:
            return GCERangeImageProfile(
                source_image=profile.source_image,
                source_machine_image=profile.source_machine_image,
                machine_type=requested_type,
                disk_size_gb=profile.disk_size_gb,
                disk_type=profile.disk_type,
                bootstrap_capability=profile.bootstrap_capability,
                domain_dns_name=profile.domain_dns_name,
                domain_netbios_name=profile.domain_netbios_name,
                participant_container_name=profile.participant_container_name,
                participant_username=profile.participant_username,
                participant_readiness_contract=profile.participant_readiness_contract,
                participant_readiness_manifest_sha256=profile.participant_readiness_manifest_sha256,
                host_ssh_username=profile.host_ssh_username,
                host_ssh_port=profile.host_ssh_port,
                allow_public_web_egress=profile.allow_public_web_egress,
                sftp_root_directory=profile.sftp_root_directory,
            )
        return profile


def load_gce_range_cell_config(*, backend: str | None = None) -> GCERangeCellConfig:
    """Load live-fire GCE configuration for the bound or selected backend.

    ``backend`` is the persisted per-range ownership binding. When supplied it
    is authoritative, so a deploy-wide selector change cannot reroute an
    in-flight operation. Direct callers may omit it to retain the environment
    selector behavior.
    """
    uses_gce = backend == "gce" if backend is not None else is_gce_range_cell_backend()
    if not uses_gce:
        raise RuntimeError("GCE range-cell config is only valid when CLOUD_PROVIDER=gcp and GCP_RANGE_BACKEND=gce")

    project_id, region, zone, service_account_email = resolve_gce_range_required_env()
    missing = missing_gce_range_required_env(
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
    range_host_identity_pool_size = _get_int_env("GCP_RANGE_HOST_IDENTITY_POOL_SIZE", 0)
    if range_host_identity_pool_size < 0:
        raise RuntimeError("GCP_RANGE_HOST_IDENTITY_POOL_SIZE must be a non-negative integer")

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
        range_host_identity_pool_size=range_host_identity_pool_size,
        linux=_load_gce_range_profile(
            "GCP_RANGE_LINUX",
            default_machine_type="e2-standard-2",
            default_disk_size_gb=50,
            # debian-12 base is ~10 GB; the Docker host default is 50 GB.
            min_disk_size_gb=10,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["ubuntu"],
        ),
        kali=_load_gce_range_profile(
            "GCP_RANGE_KALI",
            default_machine_type="e2-standard-4",
            default_disk_size_gb=80,
            # Kali (converted debian base + tools / polaris stack) needs headroom.
            min_disk_size_gb=30,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["kali"],
        ),
        windows=_load_gce_range_profile(
            "GCP_RANGE_WINDOWS",
            default_machine_type="e2-standard-4",
            # The shifter-windows image is a 100 GB disk; a boot disk cannot be
            # smaller than its source image, so the default must be >= 100 or
            # every Windows guest fails at create. Override via
            # GCP_RANGE_WINDOWS_DISK_SIZE_GB for a larger image.
            default_disk_size_gb=100,
            min_disk_size_gb=100,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["windows"],
        ),
        dc=_load_gce_range_profile(
            "GCP_RANGE_DC",
            default_machine_type="e2-standard-4",
            default_disk_size_gb=100,
            min_disk_size_gb=100,
            default_sftp_root_directory=DEFAULT_SFTP_ROOT_BY_OS["windows"],
        ),
        image_key_profiles=_load_gce_image_key_profiles(),
        portal_network_cidrs=_parse_csv_env(
            os.environ.get("PORTAL_NETWORK_CIDRS", "") or os.environ.get("PORTAL_VPC_CIDR", "")
        ),
        # Dedicated participant/operator access-workload source ranges (#1349);
        # empty falls back to portal_network_cidrs in the firewall plan.
        access_network_cidrs=_parse_csv_env(os.environ.get("ACCESS_NETWORK_CIDRS", "")),
        egress_allow_cidrs=_parse_csv_env(os.environ.get("GCP_RANGE_EGRESS_ALLOW_CIDRS", "")),
        vertex_service_account_email=os.environ.get("GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL", "").strip(),
        private_google_access=_get_bool_env("GCP_RANGE_PRIVATE_GOOGLE_ACCESS", False),
        host_mgmt_ssh_port=_get_int_env("GCP_RANGE_HOST_MGMT_SSH_PORT", 2222),
    )
