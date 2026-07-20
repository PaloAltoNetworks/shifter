"""Backend bundle contract for Shifter OSS deployments.

A *backend bundle* is the public OSS unit of backend selection (PLAT-2002): an OSS
user picks one bundle — ``aws``, ``gcp``, ``local``, ... — and that bundle owns
everything the backend needs. This module defines the *machine-readable contract*
every bundle exposes (PLAT-2003): identity/metadata, the deployment profiles it
supports, the validator for the ``settings`` it requires under
:class:`~installation.schema.RootConfig`, the runtime/infrastructure/CI outputs it
generates, the validation and health checks it runs, the cloud-neutral capabilities it
satisfies, and the repo locations it owns.

It deliberately defines the *contract*, not the bundles themselves: the provisional
``aws``/``gcp`` entries live in :mod:`installation.registry`, and a real
``settings_model`` / renderer wiring for each lands with the AWS and GCP migration
issues (#1116/#1117). The contract is data plus typed validation only — Django-free,
no domain/provider imports, no executable text (command specs are argv arrays, never
shell strings), and no secret *values* (only reference *grammars* and an output
*sensitivity* classification). Constrained by ADR-011.

Split across private submodules by responsibility and re-exported here so callers keep
using ``from installation.contract import X`` / ``installation.contract.X`` exactly as
before the split (#561):

- ``_enums``: the six contract enums plus the derived ``_SECRET_VALUE_DESTINATIONS``
  destination set.
- ``_base``: the frozen ``_ContractModel`` base and the sanitized-validation helpers
  every model below it uses.
- ``_specs``: ``CommandSpec``, ``RequiredTool``, ``RequiredSecret``.
- ``_outputs``: ``GeneratedOutput``, ``ValidationCheck``, ``HealthCheck``,
  ``OwnedFiles``.
- ``_bundle``: the top-level ``BackendBundle`` aggregate.

``_BACKEND_NAME_RE``, ``_PROFILE_RE``, ``_SECRET_NAME_RE``, and
``_SECRET_VALUE_DESTINATIONS`` are re-exported here (not just imported by the
submodule that defines them) because :mod:`installation.publication` imports them
directly from this package to mirror the contract's own grammars in the published
JSON schema.
"""

from __future__ import annotations

from ._base import (
    _CUSTOM_VALIDATOR_ERROR_TYPES,
    _SHELL_METACHARACTERS,
    _check_non_empty,
    _check_repo_relative,
    _check_unique,
    _config_issues_from_validation_error,
    _ContractModel,
    _safe_pydantic_message,
    _validate_argv_token,
)
from ._bundle import _BACKEND_NAME_RE, _PROFILE_RE, SUPPORTED_CONTRACT_VERSIONS, BackendBundle
from ._enums import (
    _SECRET_VALUE_DESTINATIONS,
    BackendCapability,
    BackendMaturity,
    OutputDestination,
    OutputKind,
    OutputSensitivity,
    ProcessRole,
)
from ._outputs import GeneratedOutput, HealthCheck, OwnedFiles, ValidationCheck
from ._specs import _EXECUTABLE_NAME_RE, _SECRET_NAME_RE, PROMPT_REFERENCE, CommandSpec, RequiredSecret, RequiredTool

__all__ = [
    "PROMPT_REFERENCE",
    "SUPPORTED_CONTRACT_VERSIONS",
    "_BACKEND_NAME_RE",
    "_CUSTOM_VALIDATOR_ERROR_TYPES",
    "_EXECUTABLE_NAME_RE",
    "_PROFILE_RE",
    "_SECRET_NAME_RE",
    "_SECRET_VALUE_DESTINATIONS",
    "_SHELL_METACHARACTERS",
    "BackendBundle",
    "BackendCapability",
    "BackendMaturity",
    "CommandSpec",
    "GeneratedOutput",
    "HealthCheck",
    "OutputDestination",
    "OutputKind",
    "OutputSensitivity",
    "OwnedFiles",
    "ProcessRole",
    "RequiredSecret",
    "RequiredTool",
    "ValidationCheck",
    "_ContractModel",
    "_check_non_empty",
    "_check_repo_relative",
    "_check_unique",
    "_config_issues_from_validation_error",
    "_safe_pydantic_message",
    "_validate_argv_token",
]
