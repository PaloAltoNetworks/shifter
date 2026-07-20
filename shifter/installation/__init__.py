"""Root installation configuration contract for Shifter OSS deployments.

A Shifter OSS deployment is configured by one root file, ``shifter.yaml``, that selects
a backend bundle and supplies deployment-level settings. This package owns that
contract: the typed root schema, a loader that fails fast with aggregated errors, the
``shifter-config`` CLI, the machine-readable backend bundle contract every backend
exposes, and the registry of known backends. Constrained by ADR-011 (OSS deployments
use root-configured backend bundles).
"""

from __future__ import annotations

from .contract import (
    PROMPT_REFERENCE,
    SUPPORTED_CONTRACT_VERSIONS,
    BackendBundle,
    BackendCapability,
    BackendMaturity,
    CommandSpec,
    GeneratedOutput,
    HealthCheck,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    OwnedFiles,
    ProcessRole,
    RequiredSecret,
    RequiredTool,
    ValidationCheck,
)
from .doctor import (
    CheckScope,
    CheckStatus,
    CheckTier,
    DoctorCheckResult,
    DoctorReport,
    check_backend,
    run_doctor,
)
from .errors import ConfigIssue, InstallationConfigError
from .loader import load_root_config, validate_root_config_file
from .publication import (
    PUBLISHED_CONTRACT_VERSION,
    build_contract_artifact,
    check_publication,
    find_incompatible_changes,
    published_backend_bundle_schema,
    serialize_artifact,
    validate_published_bundle,
)
from .registry import (
    ALLOWED_PROFILES,
    BACKEND_BUNDLES,
    KNOWN_BACKENDS,
    KNOWN_PROFILES,
    get_backend_bundle,
)
from .scaffold import ScaffoldError, ScaffoldResult, available_backends, scaffold_config
from .schema import DeploymentConfig, RootConfig

__all__ = [
    "ALLOWED_PROFILES",
    "BACKEND_BUNDLES",
    "KNOWN_BACKENDS",
    "KNOWN_PROFILES",
    "PROMPT_REFERENCE",
    "PUBLISHED_CONTRACT_VERSION",
    "SUPPORTED_CONTRACT_VERSIONS",
    "BackendBundle",
    "BackendCapability",
    "BackendMaturity",
    "CheckScope",
    "CheckStatus",
    "CheckTier",
    "CommandSpec",
    "ConfigIssue",
    "DeploymentConfig",
    "DoctorCheckResult",
    "DoctorReport",
    "GeneratedOutput",
    "HealthCheck",
    "InstallationConfigError",
    "OutputDestination",
    "OutputKind",
    "OutputSensitivity",
    "OwnedFiles",
    "ProcessRole",
    "RequiredSecret",
    "RequiredTool",
    "RootConfig",
    "ScaffoldError",
    "ScaffoldResult",
    "ValidationCheck",
    "available_backends",
    "build_contract_artifact",
    "check_backend",
    "check_publication",
    "find_incompatible_changes",
    "get_backend_bundle",
    "load_root_config",
    "published_backend_bundle_schema",
    "run_doctor",
    "scaffold_config",
    "serialize_artifact",
    "validate_published_bundle",
    "validate_root_config_file",
]
