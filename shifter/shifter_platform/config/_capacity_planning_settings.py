"""Capacity-aware provisioning Django settings (PLAT-201, #680).

Binds the deployment-owned capacity catalog and the identities used to read
provider headroom. Distinct from ``config/_capacity_settings.py``, which
configures the unrelated portal request-saturation emitter -- those metrics are
observability only and are never the capacity planner or reservation store.

The catalog itself is parsed and validated by ``shared.capacity.catalog``; this
module only reads the environment and fails closed at the composition root when
a deployment declares a catalog it cannot express. A malformed catalog is a
deployment error, so refusing to boot is preferable to silently assessing
against a partial allowlist.

``CAPACITY_PLANNING_ENABLED`` gates the whole layer so the catalog can be rolled
out and reviewed before any assessment influences provisioning.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from shared.capacity.catalog import CapacityCatalog, CapacityCatalogError, load_catalog_json

__all__ = [
    "CAPACITY_INVENTORY_ROLE_NAME",
    "CAPACITY_PLANNING_CATALOG",
    "CAPACITY_PLANNING_DEFAULT_PARTITION",
    "CAPACITY_PLANNING_ENABLED",
    "CAPACITY_PLANNING_METRICS_NAMESPACE",
]


CAPACITY_PLANNING_ENABLED = os.environ.get("CAPACITY_PLANNING_ENABLED", "False").strip().lower() == "true"

#: Name of the least-privilege, read-only role assumed in another account to
#: read its quota surface. Never the provisioner or scheduler role.
CAPACITY_INVENTORY_ROLE_NAME = os.environ.get("CAPACITY_INVENTORY_ROLE_NAME", "shifter-capacity-read").strip()

#: Partition every event is assessed against unless a caller names another.
#: Deployment-owned and allowlisted: it must name a partition the catalog
#: declares, or assessment degrades to indeterminate rather than guessing.
CAPACITY_PLANNING_DEFAULT_PARTITION = os.environ.get("CAPACITY_PLANNING_DEFAULT_PARTITION", "").strip()

#: Own CloudWatch/Cloud Monitoring namespace. Deliberately not
#: ``Shifter/PortalCapacity`` -- conflating capacity admission with portal
#: request saturation would make both series unreadable.
CAPACITY_PLANNING_METRICS_NAMESPACE = os.environ.get(
    "CAPACITY_PLANNING_METRICS_NAMESPACE", "Shifter/CapacityPlanning"
).strip()


def _load_catalog() -> CapacityCatalog:
    """Parse the declared catalog, failing closed on malformed configuration."""
    try:
        return load_catalog_json(os.environ.get("CAPACITY_PLANNING_CATALOG", ""))
    except CapacityCatalogError as exc:
        raise ImproperlyConfigured(f"CAPACITY_PLANNING_CATALOG is invalid: {exc}") from exc


CAPACITY_PLANNING_CATALOG = _load_catalog()
