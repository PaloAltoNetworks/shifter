"""Realized multi-region placement read-back for GCE range cells (#2029).

Placement is selected once, in the range-create transaction on the platform side
(``engine.services._range_placement``), and stored on the range row
(``mission_control_range.placement_zone``). The provisioner is a pure reader: it
binds the range-cell config to the stored zone and never recomputes from the
``RANGE_NETWORK_ZONES`` pool, so teardown reconstructs the exact zone the range
was placed in even if the pool is later reordered or resized. An empty stored zone
means single-zone (scalar ``RANGE_NETWORK_ZONE``) placement -- the config is left
untouched. Used symmetrically by the legacy ``gcp_range_cells`` lifecycle and the
RAES-native ``raes_range_ops`` lifecycle.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from config import GCERangeCellConfig
from provisioner_db import get_range_data_by_request_id

__all__ = ["resolve_placement_from_range_data", "resolve_range_cell_placement"]


def resolve_placement_from_range_data(config: GCERangeCellConfig, range_data: dict[str, Any]) -> GCERangeCellConfig:
    """Bind ``config`` to this range's stored placement zone.

    Returns ``config`` unchanged when no zone is stored (single-zone / pre-#2029
    range), so scalar placements and legacy rows are never re-homed. The region is
    derived from the stored zone so the two never disagree in a rendered plan.
    """
    stored = (range_data.get("placement_zone") or "").strip()
    if not stored:
        return config
    return replace(config, zone=stored, region=stored.rsplit("-", 1)[0])


def resolve_range_cell_placement(request_uuid: str, config: GCERangeCellConfig) -> GCERangeCellConfig:
    """Read the range row and bind ``config`` to its stored placement zone.

    Convenience wrapper over :func:`resolve_placement_from_range_data` for callers
    that do not already hold the range data (the RAES lifecycle). Callers that read
    the row for other fields (the legacy lifecycle reads the host pool slot too)
    should call :func:`resolve_placement_from_range_data` directly.
    """
    return resolve_placement_from_range_data(config, get_range_data_by_request_id(request_uuid))
