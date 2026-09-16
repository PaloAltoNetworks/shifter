"""Pure resolver for the tenant-managed RAES image registry (ADR-032-R2).

The registry (``engine_raes_image_mapping``, read via
``provisioner_db.get_raes_image_candidates``) maps an authored RAES image
identity (``source`` name + optional version) to a concrete provider image.
This module holds the *pure* matching rules -- exact ``(name, version)`` match,
then the any-version fallback (blank ``source_version``) -- separate from DB
access so they are trivially testable and live in exactly one place. Passthrough
of an already-concrete image ref and fail-loud on no match are the backend
realization policy (applied by the provider-specific builder), because "already
concrete" is provider-specific.

The rules live in ``shared.raes`` rather than the provisioner because two
deployables must apply them identically (#1581): the provisioner resolves images
at realization, and Scenario Editor realizability assessment resolves them in
the portal to report a missing image-supply gap *before* an author publishes. A
second copy in the portal could drift and let the editor call a pack realizable
that realization would then reject, so both execute this one module. It must
stay dependency-light -- the provisioner image copies ``shifter_platform/shared``
onto ``PYTHONPATH`` without the portal's dependencies, and ``shared.raes`` is
deliberately inert on import -- so this module imports stdlib only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolvedImage:
    """A concrete provider image resolved from the registry (ADR-032-R2)."""

    image_ref: str
    machine_type: str | None = None
    disk_size_gb: int | None = None
    disk_type: str | None = None


#: Authored version sentinels meaning "unpinned / any" (raes defaults an
#: omitted ``source.version`` to ``"*"``; a bare-string source yields no version).
_UNPINNED_VERSIONS = frozenset({"", "*"})

#: Substrings that mark an authored ``source.name`` as an already-concrete provider
#: image reference, eligible for passthrough when no registry mapping matches.
#: Keyed by registry provider because "already concrete" is provider-specific; an
#: unmodelled provider resolves to no markers and therefore never claims concrete,
#: so a new adapter must declare its own syntax rather than inherit GCE's.
_CONCRETE_REF_MARKERS: dict[str, tuple[str, ...]] = {
    "gce": ("projects/", "global/images/", "/images/family/", "https://"),
}


def is_concrete_image_ref(name: str, *, provider: str) -> bool:
    """Return whether ``name`` is already a concrete image ref for ``provider``.

    Realization passes such a reference straight through when the registry has no
    mapping for it. Editor realizability assessment applies the same rule so it
    does not report a missing-mapping gap for a pack that would in fact launch.
    """
    return any(marker in name for marker in _CONCRETE_REF_MARKERS.get(provider, ()))


def resolve_from_candidates(candidates: Sequence[dict[str, Any]], *, version: str | None) -> ResolvedImage | None:
    """Resolve a registry match from candidate rows for one (provider, source_name).

    Version handling honors authored specificity, matching raes (``version`` is
    an opaque pin with no substitution semantics) and the reference backend (which
    never substitutes an unavailable image):

    - **Unpinned** (author omitted the version, i.e. ``*``/blank): use the
      any-version default mapping (a row whose ``source_version`` is blank).
    - **Pinned** (author gave an exact version): match that ``source_version``
      exactly and **never** fall back to the any-version row -- an any-version
      catch-all cannot be proven to be the pinned artifact, so substituting it
      would silently violate authored intent.

    Returns ``None`` when nothing matches, leaving passthrough / fail-loud to the
    caller.
    """
    wanted = (version or "").strip()
    # Unpinned -> the any-version default row; pinned -> that exact version only.
    chosen = _first_match(candidates, "") if wanted in _UNPINNED_VERSIONS else _first_match(candidates, wanted)
    return _to_resolved(chosen) if chosen is not None else None


def _first_match(candidates: Sequence[dict[str, Any]], version: str) -> dict[str, Any] | None:
    """Return the first candidate whose ``source_version`` equals ``version``, else None."""
    for candidate in candidates:
        if (candidate.get("source_version") or "").strip() == version:
            return candidate
    return None


def _to_resolved(candidate: dict[str, Any]) -> ResolvedImage:
    """Build a ResolvedImage from a registry candidate row (blank sizing -> None)."""
    return ResolvedImage(
        image_ref=candidate["image_ref"],
        machine_type=(candidate.get("machine_type") or "") or None,
        disk_size_gb=candidate.get("disk_size_gb"),
        disk_type=(candidate.get("disk_type") or "") or None,
    )
