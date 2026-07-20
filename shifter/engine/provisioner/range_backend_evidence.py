"""Legacy range-backend resolution from durable ownership evidence (#1666).

A pre-#1666 range carries no persisted backend binding. On destroy/reconcile the
backend must never be guessed from the mutable ``GCP_RANGE_BACKEND`` selector
(after a ``gdc -> gce`` flip that would strand the range). This module resolves it
only from the durable ``asset_type`` discriminant persisted on the range's
``engine_instance.state`` rows; an ambiguous or evidence-free range returns
``None`` so the caller fails closed with a ``prerequisite`` diagnostic.
"""

from __future__ import annotations

import json

from provisioner_db import get_db_connection

# GDC VM Runtime asset types (VM Runtime guests + scenario pods) vs the GCE VM
# range-cell asset type -- the durable ownership discriminant on engine_instance.state.
_GDC_ASSET_TYPES = frozenset({"vm_runtime_vm", "scenario_pod"})
_GCE_ASSET_TYPE = "gce_vm"


def resolve_legacy_range_backend(request_id: str) -> str | None:
    """Resolve a legacy (NULL-binding) GCP range's backend from ownership evidence.

    Returns the proven backend only when the evidence is unambiguous (exactly one
    backend across all request-owned instances); returns ``None`` for an empty,
    mixed, or unrecognized set. Names, scenario shape, current selector, and
    successful VM boot are NOT evidence.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ei.state
            FROM engine_instance ei
            JOIN engine_request er ON ei.request_id = er.id
            WHERE er.request_id = %s
            """,
            (request_id,),
        )
        rows = cur.fetchall()

    backends: set[str] = set()
    for (state,) in rows:
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except (TypeError, ValueError):
                continue
        if not isinstance(state, dict):
            continue
        asset_type = str(state.get("asset_type", "")).strip()
        if asset_type == _GCE_ASSET_TYPE:
            backends.add("gce")
        elif asset_type in _GDC_ASSET_TYPES:
            backends.add("gdc")

    if len(backends) == 1:
        return next(iter(backends))
    return None
