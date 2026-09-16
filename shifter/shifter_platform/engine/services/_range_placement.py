"""Multi-region range-cell placement selection (#2029).

Compute CPU quota is enforced per project *per region*, so a range fleet larger
than one region's quota must span regions. ``RANGE_NETWORK_ZONES`` supplies an
ordered zone pool and a range's allocation slot picks its zone.

Placement is decided **once, in the range-create transaction** (alongside
``subnet_index``), so the realized zone is a durable property of the range from
birth: the provisioner reads it back verbatim and never recomputes from the pool.
That makes teardown correct even if the pool is later reordered or resized, and it
removes any apply-time race — creation is single and transactional. A range
created before the pool was enabled has no persisted zone and stays on the scalar
``RANGE_NETWORK_ZONE`` (the provisioner treats an empty placement as legacy
scalar). This module owns the pure selection; the provisioner side only reads the
stored value and does not import it (separate deployable).
"""

from __future__ import annotations

import os
import re

__all__ = ["range_zone_pool", "select_placement_zone"]

# A fully-qualified GCE zone is "<region>-<zone-letter>", where the region is
# "<geo>-<direction><index>" (e.g. ``us-central1-a`` -> region ``us-central1``).
_GCE_ZONE_RE = re.compile(r"^[a-z]+-[a-z]+\d+-[a-z]$")


def range_zone_pool() -> tuple[str, ...]:
    """Return the ordered, validated ``RANGE_NETWORK_ZONES`` pool (empty if unset).

    The pool is an ordered placement policy, not a set: placement is
    ``zones[slot % len(zones)]``, so a duplicate would silently weight one zone and
    reordering would change an existing range's mapping. Both are rejected here and
    declared order is preserved, so a malformed deployment fails fast with an
    authored error at range creation rather than mis-placing a cell.
    """
    zones = tuple(z.strip() for z in os.environ.get("RANGE_NETWORK_ZONES", "").split(",") if z.strip())
    seen: set[str] = set()
    for position, zone in enumerate(zones):
        if not _GCE_ZONE_RE.fullmatch(zone):
            raise RuntimeError(
                f"RANGE_NETWORK_ZONES entry {position} ({zone!r}) is not a fully-qualified GCE zone "
                "of the form '<region>-<zone-letter>' (for example 'us-central1-a')"
            )
        if zone in seen:
            raise RuntimeError(
                f"RANGE_NETWORK_ZONES entry {position} ({zone!r}) is a duplicate; the ordered pool must "
                "not repeat a zone because placement is slot % len(zones)"
            )
        seen.add(zone)
    return zones


def select_placement_zone(slot: int | None) -> str:
    """Return the pooled zone for this range's zero-based allocation slot.

    Deterministic ``zones[slot % len(zones)]``. Returns ``""`` when no pool is
    configured or the caller has no slot, meaning single-zone placement: the range
    stays on the scalar ``RANGE_NETWORK_ZONE`` and the provisioner leaves its
    config untouched.
    """
    zones = range_zone_pool()
    if not zones or slot is None:
        return ""
    return zones[slot % len(zones)]
