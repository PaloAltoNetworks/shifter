"""GCE image/sizing resolution for the RAES-native path (ADR-032-R1/R2).

Composes the backend-owned realization policy for one RAES node into a concrete
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
passed in); the candidates arrive on the operation-input projection
(``shared.raes.operation_input``), not from a registry-table read.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from shared.raes.image_policy import is_concrete_image_ref, resolve_from_candidates

from config import GCERangeImageProfile

if TYPE_CHECKING:
    from shared.raes.artifact_binding import ArtifactBinding

    from raes_plan import RaesPlanNode

_DEFAULT_MACHINE_TYPE = "e2-medium"
_DEFAULT_DISK_SIZE_GB = 30
_DEFAULT_DISK_TYPE = "pd-balanced"
_MIB_ALIGN = 256

#: Registry provider key this builder realizes against.
_GCE_PROVIDER = "gce"


class RaesGceImageError(RuntimeError):
    """Raised when an RAES node's authored image cannot be resolved for GCE."""


def resolve_gce_image(node: RaesPlanNode, candidates: Sequence[dict[str, Any]]) -> GCERangeImageProfile:
    """Resolve one RAES node's authored image + resources into a GCERangeImageProfile.

    ``candidates`` are the tenant registry rows for (gce, source_name), projected
    onto the operation input by the Engine (ADR-043 phase 5, #1837).
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
    raise RaesGceImageError(
        f"no GCE image mapping for source {image.name!r} (version {version}); register an RAES image mapping"
    )


def resolve_gce_image_from_binding(node: RaesPlanNode, binding: ArtifactBinding) -> GCERangeImageProfile:
    """Build the image profile from a generation-fenced artifact binding (ADR-034-R8).

    The Engine already resolved the authored artifact requirement to this exact
    backend-owned image at launch; the provisioner realizes it verbatim and never
    re-resolves, reads the mutable registry, chooses a different candidate, or
    falls back. Sizing gaps still fill from authored resources then profile
    defaults, exactly as for a registry-resolved image.
    """
    profile = _profile(
        node,
        binding.image_ref,
        binding.machine_type or None,
        binding.disk_size_gb,
        binding.disk_type or None,
    )
    return replace(profile, source_image_id=binding.image_id)


def _resolve_base_os(node: RaesPlanNode, candidates: Sequence[dict[str, Any]]) -> GCERangeImageProfile:
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
    raise RaesGceImageError(
        f"source-less node {node.address!r} needs a base-OS image mapping for os_family {os_family!r}"
    )


def _profile(
    node: RaesPlanNode,
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


def _machine_type_from_resources(node: RaesPlanNode) -> str | None:
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
    """Return True when ``name`` is already a concrete GCE image ref (passthrough).

    Delegates to the shared policy so editor realizability assessment and
    realization apply one rule (#1581).
    """
    return is_concrete_image_ref(name, provider=_GCE_PROVIDER)
