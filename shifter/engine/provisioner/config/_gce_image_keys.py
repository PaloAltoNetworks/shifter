"""Parsing of the bounded exact (profile class, logical key) GCE image profile map.

Reads ``GCP_RANGE_IMAGE_KEY_PROFILES_JSON`` and turns it into fully validated
``GCERangeImageProfile`` objects. Depends only on the ``_gce_profile`` leaf.
"""

import json
import os
from collections.abc import Mapping

from ._gce_profile import (
    _GCE_LOGICAL_NAME_RE,
    _GCE_PROFILE_CLASSES,
    _GCE_PROFILE_FIELDS,
    _GCE_PROFILE_MIN_DISK_SIZE_GB,
    _GCE_PROFILE_REQUIRED_FIELDS,
    GCERangeImageProfile,
    _validate_gce_range_profile,
)

_GCE_IMAGE_KEY_PROFILES_MAX_BYTES = 32_768
_GCE_IMAGE_KEY_PROFILES_MAX_ENTRIES = 64


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


def _optional_profile_string(entry: Mapping[str, object], field_name: str, *, location: str) -> str:
    """Return one optional string field from a keyed profile."""
    value = entry.get(field_name, "")
    if not isinstance(value, str):
        raise RuntimeError(f"{location}.{field_name} must be a string")
    return value.strip()


def _require_profile_entry(entry: object, *, location: str) -> Mapping[str, object]:
    """Return one keyed profile entry after checking its shape and field names."""
    if not isinstance(entry, dict):
        raise RuntimeError(f"{location} must be an object")
    fields = set(entry)
    unknown = sorted(fields - _GCE_PROFILE_FIELDS)
    missing = sorted(_GCE_PROFILE_REQUIRED_FIELDS - fields)
    if unknown:
        raise RuntimeError(f"{location} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise RuntimeError(f"{location} is missing required fields: {', '.join(missing)}")
    return entry


def _parse_profile_scalars(entry: Mapping[str, object], *, location: str) -> tuple[int, int, bool]:
    """Return the validated boot-disk size, host SSH port, and public-egress flag."""
    disk_size_gb = entry.get("disk_size_gb", 30)
    if isinstance(disk_size_gb, bool) or not isinstance(disk_size_gb, int) or disk_size_gb <= 0:
        raise RuntimeError(f"{location}.disk_size_gb must be a positive integer")
    host_ssh_port = entry.get("host_ssh_port", 22)
    if isinstance(host_ssh_port, bool) or not isinstance(host_ssh_port, int):
        raise RuntimeError(f"{location}.host_ssh_port must be an integer")
    allow_public_web_egress = entry.get("allow_public_web_egress", False)
    if not isinstance(allow_public_web_egress, bool):
        raise RuntimeError(f"{location}.allow_public_web_egress must be a boolean")
    return disk_size_gb, host_ssh_port, allow_public_web_egress


def _parse_gce_image_key_profile(
    profile_class: str,
    logical_key: str,
    entry: object,
) -> GCERangeImageProfile:
    """Parse and validate one complete logical-key GCE image profile."""
    location = f"GCP_RANGE_IMAGE_KEY_PROFILES_JSON[{profile_class!r}][{logical_key!r}]"
    values = _require_profile_entry(entry, location=location)

    source_image = _optional_profile_string(values, "source_image", location=location)
    source_machine_image = _optional_profile_string(values, "source_machine_image", location=location)
    if bool(source_image) == bool(source_machine_image):
        raise RuntimeError(f"{location} must set exactly one of source_image or source_machine_image")
    if source_image:
        missing_image_fields = sorted({"disk_size_gb", "disk_type"} - set(values))
        if missing_image_fields:
            raise RuntimeError(f"{location} is missing required fields: {', '.join(missing_image_fields)}")
    machine_type = _require_profile_string(values, "machine_type", location=location)
    bootstrap_capability = _require_profile_string(values, "bootstrap_capability", location=location)
    domain_dns_name = _optional_profile_string(values, "domain_dns_name", location=location)
    domain_netbios_name = _optional_profile_string(values, "domain_netbios_name", location=location)
    participant_container_name = _optional_profile_string(values, "participant_container_name", location=location)
    participant_username = _optional_profile_string(values, "participant_username", location=location)
    participant_readiness_contract = _optional_profile_string(
        values, "participant_readiness_contract", location=location
    )
    participant_readiness_manifest_sha256 = _optional_profile_string(
        values, "participant_readiness_manifest_sha256", location=location
    )
    host_ssh_username = _optional_profile_string(values, "host_ssh_username", location=location)
    sftp_root_directory = _optional_profile_string(values, "sftp_root_directory", location=location)
    disk_type = _optional_profile_string(values, "disk_type", location=location) or "pd-balanced"
    disk_size_gb, host_ssh_port, allow_public_web_egress = _parse_profile_scalars(values, location=location)
    if not _GCE_LOGICAL_NAME_RE.fullmatch(machine_type):
        raise RuntimeError(f"{location}.machine_type is not a valid Compute Engine machine type")

    profile = GCERangeImageProfile(
        source_image=source_image,
        source_machine_image=source_machine_image,
        machine_type=machine_type,
        disk_size_gb=disk_size_gb,
        disk_type=disk_type,
        bootstrap_capability=bootstrap_capability,
        domain_dns_name=domain_dns_name,
        domain_netbios_name=domain_netbios_name,
        participant_container_name=participant_container_name,
        participant_username=participant_username,
        participant_readiness_contract=participant_readiness_contract,
        participant_readiness_manifest_sha256=participant_readiness_manifest_sha256,
        host_ssh_username=host_ssh_username,
        host_ssh_port=host_ssh_port,
        allow_public_web_egress=allow_public_web_egress,
        sftp_root_directory=sftp_root_directory,
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
        if not _GCE_LOGICAL_NAME_RE.fullmatch(logical_key):
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
