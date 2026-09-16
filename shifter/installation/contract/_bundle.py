"""The top-level backend bundle contract model.

``BackendBundle`` (PLAT-2003). Split out of the former monolithic
``installation.contract`` module (#561) with behavior unchanged; re-exported by
:mod:`installation.contract` so the public import surface stays identical.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from ..errors import ConfigIssue, InstallationConfigError
from ._base import (
    _check_non_empty,
    _check_repo_relative,
    _check_unique,
    _config_issues_from_validation_error,
    _ContractModel,
)
from ._enums import BackendCapability, BackendMaturity
from ._outputs import GeneratedOutput, HealthCheck, OwnedFiles, ValidationCheck
from ._specs import CommandSpec, RequiredSecret, RequiredTool

# A backend or profile identifier: lowercase letter, then lowercase letters/digits and
# internal hyphens. Mirrors the DNS-label-safe style used elsewhere in this package.
_BACKEND_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]*$")

#: Backend-contract shape versions this module understands. The backend contract is
#: versioned independently of the root ``shifter.yaml`` (``RootConfig.version``) so a
#: future metadata field can be added compatibly; an unknown version fails closed.
SUPPORTED_CONTRACT_VERSIONS: tuple[int, ...] = (1,)


class BackendBundle(_ContractModel):
    """The machine-readable contract a Shifter backend bundle exposes (PLAT-2003)."""

    # ``settings_model`` holds a Pydantic model *class*, which is not a standard field
    # type, so arbitrary types are allowed for this model.
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    contract_version: int
    name: str
    title: str
    maturity: BackendMaturity
    description: str
    supported_profiles: frozenset[str]
    #: Validator for this backend's ``RootConfig.settings`` block. ``None`` means "any
    #: mapping" — the provisional ``aws``/``gcp`` registry entries until #1116/#1117.
    settings_model: type[BaseModel] | None = None
    deploy: CommandSpec | None = None
    teardown: CommandSpec | None = None
    required_tools: tuple[RequiredTool, ...] = ()
    required_secrets: tuple[RequiredSecret, ...] = ()
    generated_outputs: tuple[GeneratedOutput, ...] = ()
    validation_checks: tuple[ValidationCheck, ...] = ()
    health_checks: tuple[HealthCheck, ...] = ()
    capabilities: frozenset[BackendCapability] = frozenset()
    owned_files: OwnedFiles = OwnedFiles()
    docs: tuple[str, ...] = ()

    @field_validator("contract_version", mode="before")
    @classmethod
    def _check_contract_version(cls, v: object) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("backend contract version must be an integer")
        if v not in SUPPORTED_CONTRACT_VERSIONS:
            supported = ", ".join(str(s) for s in SUPPORTED_CONTRACT_VERSIONS)
            raise ValueError(f"unsupported backend contract version {v!r}; supported versions: {supported}")
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _BACKEND_NAME_RE.match(v):
            raise ValueError(f"backend name {v!r} must match ^[a-z][a-z0-9-]*$")
        return v

    @field_validator("title", "description")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return _check_non_empty(v)

    @field_validator("supported_profiles")
    @classmethod
    def _check_supported_profiles(cls, v: frozenset[str]) -> frozenset[str]:
        if not v:
            raise ValueError("must list at least one supported deployment profile")
        for profile in v:
            if not _PROFILE_RE.match(profile):
                raise ValueError(f"deployment profile {profile!r} must match ^[a-z][a-z0-9-]*$")
        return v

    @field_validator("docs")
    @classmethod
    def _check_docs(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_check_repo_relative(path) for path in v)

    @field_validator("settings_model")
    @classmethod
    def _check_settings_model_is_closed(cls, v: type[BaseModel] | None) -> type[BaseModel] | None:
        # The contract guarantees unknown backend settings fail before mutation, so a
        # backend's settings model must reject extras — that cannot be left to per-backend
        # convention (Pydantic ignores unknown fields by default).
        if v is not None and v.model_config.get("extra") != "forbid":
            raise ValueError(
                f"settings_model {v.__name__!r} must set model_config extra='forbid' so unknown "
                "backend settings fail closed"
            )
        return v

    @model_validator(mode="after")
    def _check_bundle_invariants(self) -> BackendBundle:
        # A setup/doctor flow preflights ``required_tools`` and then runs ``validation_checks``;
        # every check's executable must therefore appear in ``required_tools`` so the preflight
        # cannot pass and then fail on the first check.
        tool_names = {tool.name for tool in self.required_tools}
        for check in self.validation_checks:
            executable = check.command.argv[0]
            if executable not in tool_names:
                raise ValueError(
                    f"validation check {check.name!r} runs {executable!r}, which is not listed in required_tools"
                )
        for operation, command in (("deploy", self.deploy), ("teardown", self.teardown)):
            if command is not None and command.argv[0] not in tool_names:
                raise ValueError(
                    f"{operation} entrypoint runs {command.argv[0]!r}, which is not listed in required_tools"
                )
        # Named record collections are keys consumers build maps from — no duplicates.
        _check_unique((tool.name for tool in self.required_tools), field="required_tools name")
        _check_unique((secret.logical_name for secret in self.required_secrets), field="required_secrets logical_name")
        _check_unique((output.name for output in self.generated_outputs), field="generated_outputs name")
        _check_unique((check.name for check in self.validation_checks), field="validation_checks name")
        _check_unique((health.name for health in self.health_checks), field="health_checks name")
        return self

    def supports_profile(self, profile: str) -> bool:
        """Whether this backend supports the named deployment profile."""
        return profile in self.supported_profiles

    def validate_settings(self, settings: Mapping[str, object]) -> dict[str, object]:
        """Validate the ``settings`` block for this backend and return the normalized form.

        The root schema (:mod:`installation.schema`) only checks that ``settings`` is a
        mapping; the *contents* are this backend's responsibility. A bundle with no
        ``settings_model`` (the provisional ``aws``/``gcp`` entries until the migration
        issues land) accepts any mapping and returns a shallow copy. A bundle that
        supplies a model validates against it (and returns its normalized dump). On
        failure it raises :class:`~installation.errors.InstallationConfigError` with
        sanitized, ``settings``-anchored issues — never the raw Pydantic error, since the
        rejected input may be sensitive.
        """
        if self.settings_model is None:
            return dict(settings)
        try:
            validated = self.settings_model.model_validate(dict(settings))
        except ValidationError as exc:
            raise InstallationConfigError(_config_issues_from_validation_error(exc, prefix="settings")) from exc
        return dict(validated.model_dump())

    def settings_issues(self, settings: Mapping[str, object]) -> list[ConfigIssue]:
        """Validate the ``settings`` block, returning the problems found (never raises).

        Each problem is a sanitized :class:`~installation.errors.ConfigIssue` anchored
        under ``settings`` (e.g. ``settings.region``). An empty list means valid; a bundle
        with no ``settings_model`` always returns ``[]``.
        """
        try:
            self.validate_settings(settings)
        except InstallationConfigError as exc:
            return list(exc.issues)
        return []

    def secret_reference_issues(self, secrets: Mapping[str, object]) -> list[ConfigIssue]:
        """Check the ``secrets`` block against this backend's declared secrets (never raises).

        Each problem is a :class:`~installation.errors.ConfigIssue` anchored at
        ``secrets.<name>``:

        * a :class:`RequiredSecret` this backend declares with no entry in ``secrets`` —
          the renderer needs a reference for it (the value may be ``prompt`` to collect it
          at deploy time, or a provider secret name / GitHub Actions secret name / env var);
        * an entry in ``secrets`` for a logical name this backend does not use (catches
          typos before they fail at render/deploy time);
        * an entry whose value does not match the backend's ``reference_pattern`` (when
          one is declared). ``prompt`` is always accepted; a non-string value is left for
          the root schema, which already rejected it.

        A bundle with no ``required_secrets`` declared treats every supplied key as
        unknown (a backend with no secret needs none in ``shifter.yaml``).
        """
        issues: list[ConfigIssue] = []
        declared = {required.logical_name: required for required in self.required_secrets}
        for logical_name, required in declared.items():
            value = secrets.get(logical_name)
            if logical_name not in secrets:
                issues.append(
                    ConfigIssue(
                        f"secrets.{logical_name}",
                        f"is required by backend {self.name!r} but has no entry under secrets:; "
                        f"supply a reference ({required.reference_grammar})",
                    )
                )
            elif isinstance(value, str) and required.matches_reference(value) is False:
                issues.append(
                    ConfigIssue(
                        f"secrets.{logical_name}",
                        f"is not a valid reference for backend {self.name!r}; expected {required.reference_grammar}",
                    )
                )
        for supplied_name in secrets:
            if supplied_name not in declared:
                issues.append(ConfigIssue(f"secrets.{supplied_name}", f"is not a secret used by backend {self.name!r}"))
        return issues
