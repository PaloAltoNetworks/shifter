"""GCE range guest image profiles and their validation rules.

Leaf of the ``_gce`` family: owns the ``GCERangeImageProfile`` contract, the
Compute Engine reference/name grammars, and every profile validation rule.
Depends on the ``_env`` leaf and the dependency-light ``shared.sftp_root``
validator (so the SFTP root is shape-checked at config load with the same helper
the closed RAES result parser uses), so both ``_gce`` and ``_gce_image_keys`` can
build on it without a cycle.
"""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass

from shared.sftp_root import SftpRootError, normalize_sftp_root_directory

from ._env import _get_int_env

GCE_BOOTSTRAP_STANDARD = "standard"
GCE_BOOTSTRAP_POLARIS_HOST = "polaris-docker-host"
GCE_BOOTSTRAP_PREPROMOTED_DC = "prepromoted-domain-controller"
GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST = "preconfigured-machine-host"
GCE_PARTICIPANT_READINESS_CONTRACT_V1 = "participant-readiness/v1"
GCE_SUPPORTED_PARTICIPANT_READINESS_CONTRACTS = frozenset({GCE_PARTICIPANT_READINESS_CONTRACT_V1})
GCE_SUPPORTED_BOOTSTRAP_CAPABILITIES = frozenset(
    {
        GCE_BOOTSTRAP_STANDARD,
        GCE_BOOTSTRAP_POLARIS_HOST,
        GCE_BOOTSTRAP_PREPROMOTED_DC,
        GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
    }
)


@dataclass(frozen=True)
class GCERangeImageProfile:
    """Image, sizing, and realization contract for one GCE guest family."""

    source_image: str = ""
    source_machine_image: str = ""
    machine_type: str = "e2-medium"
    disk_size_gb: int = 30
    disk_type: str = "pd-balanced"
    bootstrap_capability: str = GCE_BOOTSTRAP_STANDARD
    domain_dns_name: str = ""
    domain_netbios_name: str = ""
    participant_container_name: str = ""
    participant_username: str = ""
    participant_readiness_contract: str = ""
    participant_readiness_manifest_sha256: str = ""
    host_ssh_username: str = ""
    host_ssh_port: int = 22
    allow_public_web_egress: bool = False
    # Non-secret guest-visible Guacamole SFTP root for this image (#375). Empty
    # means the image declared none; the connection layer then omits the SFTP
    # directory rather than guessing one from ``os_type``.
    sftp_root_directory: str = ""
    # Set only by a verified artifact binding, never resolved from a source alias.
    source_image_id: str = ""


def gce_image_profile_fingerprint(profile: GCERangeImageProfile) -> str:
    """Return a bounded non-secret profile identity for labels and reconciliation."""
    profile_fields = asdict(profile)
    if not profile.participant_readiness_contract and not profile.participant_readiness_manifest_sha256:
        # These fields did not exist before the participant-readiness contract.
        # Omitting their empty defaults preserves labels on every existing
        # standard, Polaris, and pre-promoted-DC guest across the rollout.
        profile_fields.pop("participant_readiness_contract")
        profile_fields.pop("participant_readiness_manifest_sha256")
    if not profile.source_image_id:
        profile_fields.pop("source_image_id")
    canonical = json.dumps(profile_fields, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


# Disk types the range provisioner accepts. Compute Engine rejects an unknown
# disk type only after the create call; validate at config load so the operator
# sees a clear error before a range attempt (#1343 gap 7).
_VALID_GCE_DISK_TYPES = frozenset({"pd-standard", "pd-balanced", "pd-ssd", "pd-extreme", "hyperdisk-balanced"})
_GCE_PROFILE_CLASSES = frozenset({"linux", "kali", "windows", "dc"})
_GCE_PROFILE_REQUIRED_FIELDS = frozenset({"machine_type", "bootstrap_capability"})
_GCE_PROFILE_OPTIONAL_FIELDS = frozenset(
    {
        "source_image",
        "source_machine_image",
        "disk_size_gb",
        "disk_type",
        "domain_dns_name",
        "domain_netbios_name",
        "participant_container_name",
        "participant_username",
        "participant_readiness_contract",
        "participant_readiness_manifest_sha256",
        "host_ssh_username",
        "host_ssh_port",
        "allow_public_web_egress",
        "sftp_root_directory",
    }
)
_GCE_PROFILE_FIELDS = _GCE_PROFILE_REQUIRED_FIELDS | _GCE_PROFILE_OPTIONAL_FIELDS
_GCE_PROFILE_MIN_DISK_SIZE_GB = {"linux": 10, "kali": 30, "windows": 100, "dc": 100}
_GCE_LOGICAL_NAME_RE = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")

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
_GCE_MACHINE_IMAGE_REFERENCE_RE = re.compile(
    rf"^(?:(?:https://[^/]+/compute/(?:v1|beta)/)?)projects/{_GCE_PROJECT}/global/machineImages/{_GCE_NAME}$"
)
_GCE_LINUX_USERNAME_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
_GCE_CONTAINER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _profile_has_source(profile: GCERangeImageProfile) -> bool:
    """Return whether a profile selects exactly one supported GCE source."""
    return bool(profile.source_image or profile.source_machine_image)


def _validate_gce_image_reference(prefix: str, value: str) -> None:
    """Reject a malformed GCE image reference before any Compute Engine call."""
    if not _GCE_IMAGE_REFERENCE_RE.fullmatch(value):
        raise RuntimeError(
            f"{prefix}_IMAGE is not a valid Compute Engine image reference: {value!r}. "
            "Use an image/family name, 'family/<name>', or "
            "'projects/<project>/global/images[/family]/<name>'."
        )


def _validate_gce_machine_image_reference(prefix: str, value: str) -> None:
    """Require an exact, immutable Compute Engine machine-image resource."""
    if not _GCE_MACHINE_IMAGE_REFERENCE_RE.fullmatch(value):
        raise RuntimeError(
            f"{prefix}.source_machine_image is not a valid exact Compute Engine machine-image reference: "
            f"{value!r}. Use 'projects/<project>/global/machineImages/<name>'."
        )


def _reject_machine_host_fields(prefix: str, profile: GCERangeImageProfile, machine_fields: tuple[str, ...]) -> None:
    """Reject machine-host-only fields on a profile without that capability."""
    if profile.source_machine_image or any(machine_fields) or profile.host_ssh_port != 22:
        raise RuntimeError(
            f"{prefix} machine-image and participant-container fields require "
            f"bootstrap_capability={GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST!r}"
        )


def _validate_machine_host_identity(prefix: str, profile: GCERangeImageProfile) -> None:
    """Validate the container name, Linux usernames, and host SSH port of a machine host."""
    if not _GCE_CONTAINER_NAME_RE.fullmatch(profile.participant_container_name):
        raise RuntimeError(f"{prefix}.participant_container_name is not a valid container name")
    for field_name, value in (
        ("participant_username", profile.participant_username),
        ("host_ssh_username", profile.host_ssh_username),
    ):
        if not _GCE_LINUX_USERNAME_RE.fullmatch(value):
            raise RuntimeError(f"{prefix}.{field_name} is not a valid Linux username")
    if profile.host_ssh_port < 1 or profile.host_ssh_port > 65535:
        raise RuntimeError(f"{prefix}.host_ssh_port must be between 1 and 65535")


def _validate_preconfigured_machine_profile(prefix: str, profile: GCERangeImageProfile) -> None:
    """Validate the closed machine-host capability fields."""
    identity_fields = (
        profile.participant_container_name,
        profile.participant_username,
        profile.host_ssh_username,
    )
    readiness_fields = (
        profile.participant_readiness_contract,
        profile.participant_readiness_manifest_sha256,
    )
    machine_fields = identity_fields + readiness_fields
    if profile.bootstrap_capability != GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
        _reject_machine_host_fields(prefix, profile, machine_fields)
        return
    if not profile.source_machine_image:
        raise RuntimeError(f"{prefix} preconfigured-machine-host requires source_machine_image")
    if not all(identity_fields):
        raise RuntimeError(
            f"{prefix} preconfigured-machine-host requires participant_container_name, "
            "participant_username, and host_ssh_username"
        )
    if not all(readiness_fields):
        raise RuntimeError(
            f"{prefix} preconfigured-machine-host requires participant_readiness_contract "
            "and participant_readiness_manifest_sha256"
        )
    if profile.participant_readiness_contract not in GCE_SUPPORTED_PARTICIPANT_READINESS_CONTRACTS:
        raise RuntimeError(
            f"{prefix}.participant_readiness_contract is unsupported; choose one of: "
            f"{', '.join(sorted(GCE_SUPPORTED_PARTICIPANT_READINESS_CONTRACTS))}"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", profile.participant_readiness_manifest_sha256):
        raise RuntimeError(f"{prefix}.participant_readiness_manifest_sha256 must be a lowercase SHA-256 digest")
    _validate_machine_host_identity(prefix, profile)


def _validate_gce_profile_source(prefix: str, profile: GCERangeImageProfile, *, min_disk_size_gb: int) -> None:
    """Fail fast on a malformed image ref, unknown disk type, or too-small boot disk."""
    if profile.source_image and profile.source_machine_image:
        raise RuntimeError(f"{prefix} must set exactly one of source_image or source_machine_image")
    if profile.source_machine_image:
        _validate_gce_machine_image_reference(prefix, profile.source_machine_image)
    if not profile.source_image:
        return
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


def _validate_gce_profile_domain(prefix: str, profile: GCERangeImageProfile) -> None:
    """Validate the bootstrap capability slug and the paired AD domain names."""
    if not _GCE_LOGICAL_NAME_RE.fullmatch(profile.bootstrap_capability):
        raise RuntimeError(
            f"{prefix}.bootstrap_capability must be a lowercase logical capability using letters, digits, and hyphens"
        )
    if bool(profile.domain_dns_name) != bool(profile.domain_netbios_name):
        raise RuntimeError(f"{prefix} must set domain_dns_name and domain_netbios_name together")
    if len(profile.domain_dns_name) > 253:
        raise RuntimeError(f"{prefix}.domain_dns_name exceeds the 253-character DNS-name limit")
    if len(profile.domain_netbios_name) > 15:
        raise RuntimeError(f"{prefix}.domain_netbios_name exceeds the 15-character NetBIOS-name limit")


def _validate_gce_profile_sftp_root(prefix: str, profile: GCERangeImageProfile) -> None:
    """Reject a malformed SFTP root before it can reach the realized instance."""
    if not profile.sftp_root_directory:
        return
    try:
        normalize_sftp_root_directory(profile.sftp_root_directory)
    except SftpRootError as exc:
        raise RuntimeError(f"{prefix}.sftp_root_directory is invalid: {exc}") from exc


def _validate_gce_range_profile(prefix: str, profile: GCERangeImageProfile, *, min_disk_size_gb: int) -> None:
    """Fail fast on any malformed field of one resolved GCE range guest profile."""
    _validate_gce_profile_source(prefix, profile, min_disk_size_gb=min_disk_size_gb)
    _validate_gce_profile_domain(prefix, profile)
    _validate_preconfigured_machine_profile(prefix, profile)
    _validate_gce_profile_sftp_root(prefix, profile)


def _load_gce_range_profile(
    prefix: str,
    *,
    default_machine_type: str,
    default_disk_size_gb: int,
    min_disk_size_gb: int,
    default_sftp_root_directory: str = "",
) -> GCERangeImageProfile:
    """Load one GCE range guest image/sizing profile."""
    profile = GCERangeImageProfile(
        source_image=os.environ.get(f"{prefix}_IMAGE", "").strip(),
        machine_type=os.environ.get(f"{prefix}_MACHINE_TYPE", default_machine_type).strip() or default_machine_type,
        disk_size_gb=_get_int_env(f"{prefix}_DISK_SIZE_GB", default_disk_size_gb),
        disk_type=os.environ.get(f"{prefix}_DISK_TYPE", "pd-balanced").strip() or "pd-balanced",
        sftp_root_directory=os.environ.get(f"{prefix}_SFTP_ROOT_DIRECTORY", default_sftp_root_directory).strip(),
    )
    _validate_gce_range_profile(prefix, profile, min_disk_size_gb=min_disk_size_gb)
    return profile


__all__ = [
    "GCE_BOOTSTRAP_POLARIS_HOST",
    "GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST",
    "GCE_BOOTSTRAP_PREPROMOTED_DC",
    "GCE_BOOTSTRAP_STANDARD",
    "GCE_SUPPORTED_BOOTSTRAP_CAPABILITIES",
    "GCERangeImageProfile",
    "gce_image_profile_fingerprint",
]
