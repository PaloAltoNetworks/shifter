"""CMS models — bounded-context package.

Public surface is preserved as ``from cms.models import X``. Internally the
classes are organized by bounded context:

* :mod:`cms.models.catalogs`     — CatalogBase + reference data (types, OS, agent enum)
* :mod:`cms.models.assets`       — User-owned assets, credentials, agent installers
* :mod:`cms.models.provisioning` — Request and the entities a request materializes
* :mod:`cms.models.scenarios`    — Scenario templates and metadata overlays
* :mod:`cms.models.range`        — Engine-side range tracking

New CMS models go into the submodule that matches their domain. Always re-export
them here so existing call sites (`from cms.models import X`) keep working.
"""

from cms.models.assets import (
    AgentConfig,
    Asset,
    Credential,
    CredentialBase,
    FileAsset,
)
from cms.models.catalogs import (
    AgentType,
    AppType,
    CatalogBase,
    CredentialType,
    InstanceType,
    OperatingSystem,
)
from cms.models.provisioning import (
    App,
    EntityBase,
    Instance,
    Request,
    Subnet,
)
from cms.models.range import (
    ActiveRangeInstanceManager,
    RangeInstance,
)
from cms.models.scenarios import Scenario, ScenarioMetadata

__all__ = [
    "ActiveRangeInstanceManager",
    "AgentConfig",
    "AgentType",
    "App",
    "AppType",
    "Asset",
    "CatalogBase",
    "Credential",
    "CredentialBase",
    "CredentialType",
    "EntityBase",
    "FileAsset",
    "Instance",
    "InstanceType",
    "OperatingSystem",
    "RangeInstance",
    "Request",
    "Scenario",
    "ScenarioMetadata",
    "Subnet",
]
