"""Root installation configuration contract for Shifter OSS deployments.

A Shifter OSS deployment is configured by one root file, ``shifter.yaml``, that
selects a backend bundle and supplies deployment-level settings. This package owns
that contract: the typed schema, a loader that fails fast with aggregated errors, and
the ``shifter-config`` CLI. Constrained by ADR-011 (OSS deployments use
root-configured backend bundles).
"""

from __future__ import annotations

from .backends import ALLOWED_PROFILES, KNOWN_BACKENDS, KNOWN_PROFILES
from .errors import ConfigIssue, InstallationConfigError
from .loader import load_root_config, validate_root_config_file
from .schema import DeploymentConfig, RootConfig

__all__ = [
    "ALLOWED_PROFILES",
    "KNOWN_BACKENDS",
    "KNOWN_PROFILES",
    "ConfigIssue",
    "DeploymentConfig",
    "InstallationConfigError",
    "RootConfig",
    "load_root_config",
    "validate_root_config_file",
]
