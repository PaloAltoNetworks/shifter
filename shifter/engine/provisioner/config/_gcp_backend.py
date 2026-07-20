"""GCP range-backend selection (``gce`` vs ``gdc``).

Hoisted to its own leaf module (rather than living in ``_gce.py`` or
``_gdc.py`` as the domain split would naively suggest) because both the GCE
and GDC domains need it, *and* ``_gce.py`` also needs ``_range.py``'s
``get_range_availability_zone``. Keeping backend selection here -- depending
only on ``_crypto`` -- keeps the dependency graph one-directional:
``_gcp_backend`` -> {``_gdc``, ``_range``} -> ``_gce``, with no cycle.
"""

import os

from shared.range_instantiation_policy import GcpRangeBackendError, normalize_gcp_range_backend

from ._crypto import resolve_cloud_provider


def get_gcp_range_backend() -> str:
    """Return the selected GCP range backend.

    GCE range cells are the default GCP path, so ``gce`` is assumed whenever
    ``CLOUD_PROVIDER=gcp`` and no explicit backend is configured. The historical
    GDC VM Runtime path remains fully supported and is selected explicitly with
    ``GCP_RANGE_BACKEND=gdc`` (a one-line rollback for any environment).
    """
    if resolve_cloud_provider() != "gcp":
        return ""
    # The gce/gdc parse lives once in shared.range_instantiation_policy (#1348);
    # preserve the historical RuntimeError contract for provisioner callers.
    try:
        return normalize_gcp_range_backend(
            os.environ.get("GCP_RANGE_BACKEND"),
            os.environ.get("GCP_RANGE_PLANE"),
        )
    except GcpRangeBackendError as exc:
        raise RuntimeError(str(exc)) from exc


def _is_active_gdc_range_plane() -> bool:
    """Return True when the configured GCP range backend is the GDC VM Runtime."""
    return get_gcp_range_backend() == "gdc"


def is_gce_range_cell_backend() -> bool:
    """Return True when GCP ranges should be provisioned as GCE range cells."""
    return get_gcp_range_backend() == "gce"
