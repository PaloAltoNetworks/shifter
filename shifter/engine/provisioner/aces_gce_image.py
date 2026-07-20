"""GCE image/sizing resolution for the ACES-native path (ADR-032-R1/R2).

Composes the backend-owned realization policy for one ACES node into a concrete
``GCERangeImageProfile`` (source image + machine type + disk), keyed on the
*authored* identity (image ``source`` + ``resources``), never on os_family:

1. Resolve the authored image ``source`` (name + version) against the
   tenant-managed registry candidates (exact pin, else the any-version default).
2. If no registry mapping exists but the authored ``source.name`` is already a
   concrete GCE image reference, pass it through.
3. Otherwise fail loud -- never guess an image from os_family for an *authored*
   source.

A node that declares **no** source is different: it still needs a boot OS, so the
backend supplies a base image from the registry keyed on ``os_family`` (ADR-032 --
a base-OS default for a source-less node is legitimate backend policy, not the
prohibited "sniff an authored source to hardcode a scenario"). Fails loud when no
base image is registered for the os_family.

Machine type precedence: the registry entry's ``machine_type`` (a tenant-pinned
size) wins; otherwise the authored ``resources`` (vcpus + ram) derive a GCE
custom machine type; otherwise the profile default. Disk falls back to the
profile default when the registry entry omits it. This is pure (candidates are
passed in); the DB read lives in ``provisioner_db.get_aces_image_candidates``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from aces_image_resolver import resolve_from_candidates
from config import GCERangeImageProfile

if TYPE_CHECKING:
    from aces_plan import AcesPlanNode

_DEFAULT_MACHINE_TYPE = "e2-medium"
_DEFAULT_DISK_SIZE_GB = 30
_DEFAULT_DISK_TYPE = "pd-balanced"
_MIB_ALIGN = 256

# Substrings that mark ``source.name`` as an already-concrete GCE image reference
# (a full/partial self-link or family URL), eligible for passthrough.
_CONCRETE_GCE_REF_MARKERS = ("projects/", "global/images/", "/images/family/", "https://")


class AcesGceImageError(RuntimeError):
    """Raised when an ACES node's authored image cannot be resolved for GCE."""


def resolve_gce_image(node: AcesPlanNode, candidates: Sequence[dict[str, Any]]) -> GCERangeImageProfile:
    """Resolve one ACES node's authored image + resources into a GCERangeImageProfile.

    ``candidates`` are the tenant registry rows for (gce, source_name), as returned
    by ``provisioner_db.get_aces_image_candidates``.
    """
    image = node.image
    if image is None or not image.name:
        return _resolve_base_os(node, candidates)

    resolved = resolve_from_candidates(candidates, version=image.version)
    if resolved is not None:
        return _profile(node, resolved.image_ref, resolved.machine_type, resolved.disk_size_gb, resolved.disk_type)

    if _is_concrete_gce_ref(image.name):
        return _profile(node, image.name)

    version = image.version or "*"
    raise AcesGceImageError(
        f"no GCE image mapping for source {image.name!r} (version {version}); register an ACES image mapping"
    )


def _resolve_base_os(node: AcesPlanNode, candidates: Sequence[dict[str, Any]]) -> GCERangeImageProfile:
    """Resolve a base OS image for a source-less node from its os_family.

    A node that declares no ``source`` still needs a boot OS, so the backend
    supplies one from the tenant registry keyed on ``os_family`` (the caller
    passes the os_family candidates). Per ADR-032 this base-OS default for a
    source-*less* node is legitimate backend policy, distinct from sniffing an
    *authored* source to hardcode a scenario (which is prohibited). Fails loud when
    no base image is registered for the os_family.
    """
    resolved = resolve_from_candidates(candidates, version=None)
    if resolved is not None:
        return _profile(node, resolved.image_ref, resolved.machine_type, resolved.disk_size_gb, resolved.disk_type)
    os_family = node.os_family or "linux"
    raise AcesGceImageError(
        f"source-less node {node.address!r} needs a base-OS image mapping for os_family {os_family!r}"
    )


def _profile(
    node: AcesPlanNode,
    source_image: str,
    machine_type: str | None = None,
    disk_size_gb: int | None = None,
    disk_type: str | None = None,
) -> GCERangeImageProfile:
    """Build a GCERangeImageProfile, filling gaps from authored resources then defaults."""
    return GCERangeImageProfile(
        source_image=source_image,
        machine_type=machine_type or _machine_type_from_resources(node) or _DEFAULT_MACHINE_TYPE,
        disk_size_gb=disk_size_gb or _DEFAULT_DISK_SIZE_GB,
        disk_type=disk_type or _DEFAULT_DISK_TYPE,
    )


def _machine_type_from_resources(node: AcesPlanNode) -> str | None:
    """Derive a GCE custom machine type from authored resources, or None.

    Uses ``e2-custom-<vcpus>-<ram_mib>`` with ram aligned up to a 256 MiB boundary
    (a Compute Engine custom-memory constraint). Only produced when both vcpus and
    ram are authored; otherwise the caller falls back to a registry/profile size.
    """
    if not node.vcpus or not node.ram_mib:
        return None
    aligned_ram = ((node.ram_mib + _MIB_ALIGN - 1) // _MIB_ALIGN) * _MIB_ALIGN
    return f"e2-custom-{node.vcpus}-{aligned_ram}"


def _is_concrete_gce_ref(name: str) -> bool:
    """Return True when ``name`` is already a concrete GCE image ref (passthrough)."""
    return any(marker in name for marker in _CONCRETE_GCE_REF_MARKERS)
