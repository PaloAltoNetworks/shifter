"""GCE (Compute Engine) live-fire range-cell backend configuration.

Depends on the ``_env`` leaf, the ``_gcp_backend`` leaf, and ``_range`` (for
``get_range_availability_zone``).
"""

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from ._env import _get_bool_env, _get_int_env, _parse_csv_env
from ._gcp_backend import is_gce_range_cell_backend
from ._range import get_range_availability_zone


@dataclass(frozen=True)
class GCERangeImageProfile:
    """Image and sizing contract for one Compute Engine range guest family."""

    source_image: str = ""
    machine_type: str = "e2-medium"
    disk_size_gb: int = 30
    disk_type: str = "pd-balanced"


def gce_image_profile_fingerprint(profile: GCERangeImageProfile) -> str:
    """Return a bounded non-secret profile identity for labels and reconciliation."""
    canonical = json.dumps(asdict(profile), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


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
            profile = self.kali if self.kali.source_image else self.linux
        elif os_type == "windows":
            profile_class = "windows"
            profile = self.windows
        else:
            profile_class = "linux"
            profile = self.linux

        logical_key = ami_key.strip()
        if logical_key:
            if not _GCE_IMAGE_KEY_RE.fullmatch(logical_key):
                raise RuntimeError("GCE ami_key must be a lowercase logical key using letters, digits, and hyphens")
            mapped_profile = self.image_key_profiles.get(profile_class, {}).get(logical_key)
            if mapped_profile is None:
                raise RuntimeError(
                    "There is no configured GCE image profile for "
                    f"profile_class={profile_class!r} ami_key={logical_key!r}; "
                    "set GCP_RANGE_IMAGE_KEY_PROFILES_JSON before launching this scenario."
                )
            profile = mapped_profile

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


# Disk types the range provisioner accepts. Compute Engine rejects an unknown
# disk type only after the create call; validate at config load so the operator
# sees a clear error before a range attempt (#1343 gap 7).
_VALID_GCE_DISK_TYPES = frozenset({"pd-standard", "pd-balanced", "pd-ssd", "pd-extreme", "hyperdisk-balanced"})
_GCE_PROFILE_CLASSES = frozenset({"linux", "kali", "windows", "dc"})
_GCE_PROFILE_FIELDS = frozenset({"source_image", "machine_type", "disk_size_gb", "disk_type"})
_GCE_PROFILE_MIN_DISK_SIZE_GB = {"linux": 10, "kali": 30, "windows": 100, "dc": 100}
_GCE_IMAGE_KEY_PROFILES_MAX_BYTES = 32_768
_GCE_IMAGE_KEY_PROFILES_MAX_ENTRIES = 64
_GCE_IMAGE_KEY_RE = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
_GCE_MACHINE_TYPE_RE = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")

# A Compute Engine resource name segment: lowercase, starts with a letter, and
# is at most 63 chars (RFC1035, as GCE enforces for image/family names).
_GCE_NAME = r"[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?"
# A project id segment permits the domain-scoped ``example.com:project`` legacy
# form, so allow dots and a single colon in addition to the standard chars.
_GCE_PROJECT = r"[a-z0-9][-a-z0-9.:]*"
# Accepted image reference forms:
#   <name>                                         (bare image or family slug)
#   family/<name>
#   [global|projects/<proj>/global]/images[/family]/<name>
#   an https://…/compute/v1/ prefix on the projects/… form
_GCE_IMAGE_REFERENCE_RE = re.compile(
    r"^(?:"
    rf"{_GCE_NAME}"
    rf"|family/{_GCE_NAME}"
    rf"|(?:https://[^/]+/compute/(?:v1|beta)/)?"
    rf"(?:projects/{_GCE_PROJECT}/)?global/images/(?:family/)?{_GCE_NAME}"
    r")$"
)


def _validate_gce_image_reference(prefix: str, value: str) -> None:
    """Reject a malformed GCE image reference before any Compute Engine call."""
    if not _GCE_IMAGE_REFERENCE_RE.fullmatch(value):
        raise RuntimeError(
            f"{prefix}_IMAGE is not a valid Compute Engine image reference: {value!r}. "
            "Use an image/family name, 'family/<name>', or "
            "'projects/<project>/global/images[/family]/<name>'."
        )


def _validate_gce_range_profile(prefix: str, profile: GCERangeImageProfile, *, min_disk_size_gb: int) -> None:
    """Fail fast on a malformed image ref, unknown disk type, or too-small boot disk."""
    if profile.source_image:
        _validate_gce_image_reference(prefix, profile.source_image)
    if profile.disk_type not in _VALID_GCE_DISK_TYPES:
        raise RuntimeError(
            f"{prefix}_DISK_TYPE {profile.disk_type!r} is not a supported Compute Engine disk type. "
            f"Choose one of: {', '.join(sorted(_VALID_GCE_DISK_TYPES))}."
        )
    # Role-policy minimum boot-disk size. This is NOT a guarantee that the disk
    # is >= the actual source image's disk (that would require resolving image
    # metadata at create time, and the reference may be a mutable family); it
    # enforces the documented per-role floors (e.g. the Windows/DC images are
    # 100 GB) so an obviously-undersized disk fails at config load instead of
    # only at instance creation.
    if profile.disk_size_gb < min_disk_size_gb:
        raise RuntimeError(
            f"{prefix}_DISK_SIZE_GB {profile.disk_size_gb} is smaller than the {min_disk_size_gb} GB "
            f"role-policy minimum for this guest role."
        )


def _load_gce_range_profile(
    prefix: str,
    *,
    default_machine_type: str,
    default_disk_size_gb: int,
    min_disk_size_gb: int,
) -> GCERangeImageProfile:
    """Load one GCE range guest image/sizing profile."""
    profile = GCERangeImageProfile(
        source_image=os.environ.get(f"{prefix}_IMAGE", "").strip(),
        machine_type=os.environ.get(f"{prefix}_MACHINE_TYPE", default_machine_type).strip() or default_machine_type,
        disk_size_gb=_get_int_env(f"{prefix}_DISK_SIZE_GB", default_disk_size_gb),
        disk_type=os.environ.get(f"{prefix}_DISK_TYPE", "pd-balanced").strip() or "pd-balanced",
    )
    _validate_gce_range_profile(prefix, profile, min_disk_size_gb=min_disk_size_gb)
    return profile


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one JSON object while refusing keys that would otherwise be overwritten."""
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _require_profile_string(entry: Mapping[str, object], field_name: str, *, location: str) -> str:
    """Return one required non-empty string field from a keyed profile."""
    value = entry[field_name]
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{location}.{field_name} must be a non-empty string")
    return value.strip()


def _parse_gce_image_key_profile(
    profile_class: str,
    logical_key: str,
    entry: object,
) -> GCERangeImageProfile:
    """Parse and validate one complete logical-key GCE image profile."""
    location = f"GCP_RANGE_IMAGE_KEY_PROFILES_JSON[{profile_class!r}][{logical_key!r}]"
    if not isinstance(entry, dict):
        raise RuntimeError(f"{location} must be an object")
    fields = set(entry)
    unknown = sorted(fields - _GCE_PROFILE_FIELDS)
    missing = sorted(_GCE_PROFILE_FIELDS - fields)
    if unknown:
        raise RuntimeError(f"{location} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise RuntimeError(f"{location} is missing required fields: {', '.join(missing)}")

    source_image = _require_profile_string(entry, "source_image", location=location)
    machine_type = _require_profile_string(entry, "machine_type", location=location)
    disk_type = _require_profile_string(entry, "disk_type", location=location)
    disk_size_gb = entry["disk_size_gb"]
    if isinstance(disk_size_gb, bool) or not isinstance(disk_size_gb, int) or disk_size_gb <= 0:
        raise RuntimeError(f"{location}.disk_size_gb must be a positive integer")
    if not _GCE_MACHINE_TYPE_RE.fullmatch(machine_type):
        raise RuntimeError(f"{location}.machine_type is not a valid Compute Engine machine type")

    profile = GCERangeImageProfile(
        source_image=source_image,
        machine_type=machine_type,
        disk_size_gb=disk_size_gb,
        disk_type=disk_type,
    )
    _validate_gce_range_profile(
        location,
        profile,
        min_disk_size_gb=_GCE_PROFILE_MIN_DISK_SIZE_GB[profile_class],
    )
    return profile


def _load_gce_image_key_profile_class(
    profile_class: str,
    entries: object,
    *,
    entry_count: int,
) -> tuple[dict[str, GCERangeImageProfile], int]:
    """Parse one profile class's logical-key entries, enforcing the global entry cap.

    ``entry_count`` is the running total across all classes; the updated total is
    returned so the caller can keep the cap cumulative.
    """
    if not isinstance(entries, dict):
        raise RuntimeError(f"GCP_RANGE_IMAGE_KEY_PROFILES_JSON[{profile_class!r}] must be an object")
    resolved_entries: dict[str, GCERangeImageProfile] = {}
    for logical_key, entry in entries.items():
        if not _GCE_IMAGE_KEY_RE.fullmatch(logical_key):
            raise RuntimeError(
                "GCP_RANGE_IMAGE_KEY_PROFILES_JSON logical keys must be lowercase and use only "
                "letters, digits, and hyphens"
            )
        entry_count += 1
        if entry_count > _GCE_IMAGE_KEY_PROFILES_MAX_ENTRIES:
            raise RuntimeError("GCP_RANGE_IMAGE_KEY_PROFILES_JSON exceeds the 64-entry limit")
        resolved_entries[logical_key] = _parse_gce_image_key_profile(profile_class, logical_key, entry)
    return resolved_entries, entry_count


def _load_gce_image_key_profiles() -> dict[str, dict[str, GCERangeImageProfile]]:
    """Load the bounded exact (profile class, logical key) GCE profile map."""
    raw = os.environ.get("GCP_RANGE_IMAGE_KEY_PROFILES_JSON", "").strip()
    if not raw:
        return {}
    if len(raw.encode("utf-8")) > _GCE_IMAGE_KEY_PROFILES_MAX_BYTES:
        raise RuntimeError("GCP_RANGE_IMAGE_KEY_PROFILES_JSON exceeds the 32768-byte configuration limit")
    try:
        # json.JSONDecodeError is a ValueError subclass, so this also catches the
        # duplicate-key ValueError raised by _reject_duplicate_json_keys.
        decoded = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except ValueError as exc:
        raise RuntimeError(f"GCP_RANGE_IMAGE_KEY_PROFILES_JSON must be a valid JSON object: {exc}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("GCP_RANGE_IMAGE_KEY_PROFILES_JSON must be a valid JSON object")

    unknown_classes = sorted(set(decoded) - _GCE_PROFILE_CLASSES)
    if unknown_classes:
        raise RuntimeError(
            "GCP_RANGE_IMAGE_KEY_PROFILES_JSON has unknown profile classes: " + ", ".join(unknown_classes)
        )

    profiles: dict[str, dict[str, GCERangeImageProfile]] = {}
    entry_count = 0
    for profile_class, entries in decoded.items():
        profiles[profile_class], entry_count = _load_gce_image_key_profile_class(
            profile_class, entries, entry_count=entry_count
        )
    return profiles


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
            # debian-12 base is ~10 GB; the Docker host default is 50 GB.
            min_disk_size_gb=10,
        ),
        kali=_load_gce_range_profile(
            "GCP_RANGE_KALI",
            default_machine_type="e2-standard-4",
            default_disk_size_gb=80,
            # Kali (converted debian base + tools / polaris stack) needs headroom.
            min_disk_size_gb=30,
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
        ),
        dc=_load_gce_range_profile(
            "GCP_RANGE_DC",
            default_machine_type="e2-standard-4",
            default_disk_size_gb=100,
            min_disk_size_gb=100,
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
