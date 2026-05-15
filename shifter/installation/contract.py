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
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .errors import ConfigIssue, InstallationConfigError

# A backend or profile identifier: lowercase letter, then lowercase letters/digits and
# internal hyphens. Mirrors the DNS-label-safe style used elsewhere in this package.
_BACKEND_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
# A logical secret name — the same grammar as the keys of ``RootConfig.secrets`` — so a
# bundle's required secret can be matched against what the user supplied.
_SECRET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# A bare executable name resolved on PATH (no path separators, no spaces): the argv[0] of
# a command spec and the name of a ``RequiredTool`` — e.g. ``terraform``, ``uv``,
# ``python3``. A consumer must be able to tell a structured argv from a shell fragment, so
# the executable element is held to this grammar rather than free-form text. ``\w`` is the
# ASCII word-character class here (``re.ASCII``), then word characters plus ``.`` / ``-``.
_EXECUTABLE_NAME_RE = re.compile(r"^\w[\w.-]*$", re.ASCII)
# Characters that would let an argv element be (mis)interpreted as a shell fragment if
# anyone ever ``str.join``'d the argv array and handed it to a shell. Registry command
# specs are argv arrays executed *without* a shell; rejecting these (and any internal
# whitespace) keeps a shell fragment out of the registry data itself.
_SHELL_METACHARACTERS = frozenset(";&|`$<>\n\r")

#: Backend-contract shape versions this module understands. The backend contract is
#: versioned independently of the root ``shifter.yaml`` (``RootConfig.version``) so a
#: future metadata field can be added compatibly; an unknown version fails closed.
SUPPORTED_CONTRACT_VERSIONS: tuple[int, ...] = (1,)

#: The universal "supply this at deploy time" reference value: a ``secrets`` entry whose
#: value is ``prompt`` declares the secret without committing a concrete reference; it is
#: a valid reference for every backend regardless of that backend's ``reference_pattern``.
PROMPT_REFERENCE = "prompt"  # nosec B105 - the literal "prompt" sentinel, not a credential


class BackendMaturity(StrEnum):
    """How production-ready a backend bundle is."""

    EXPERIMENTAL = "experimental"
    BETA = "beta"
    STABLE = "stable"
    DEPRECATED = "deprecated"


class OutputSensitivity(StrEnum):
    """How a generated output must be handled.

    ``PUBLIC`` values may appear in ConfigMaps, generated docs, and dry-run output;
    ``SECRET_REFERENCE`` values are pointers (a provider secret name, a GitHub Actions
    secret name, an env var, or ``prompt``); ``SECRET_VALUE`` is the secret material
    itself and must stay in a secret store or Kubernetes Secret — never a ConfigMap,
    log, dry-run, or plan comment.
    """

    PUBLIC = "public"
    # These are classification labels for *how an output is handled*, not credentials —
    # silence the "hardcoded password" heuristics that fire on the SECRET_ prefix.
    SECRET_REFERENCE = "secret-reference"  # noqa: S105 # nosec B105
    SECRET_VALUE = "secret-value"  # noqa: S105 # nosec B105


class ProcessRole(StrEnum):
    """Which Shifter process a generated runtime output is for."""

    PORTAL = "portal"
    WORKER = "worker"
    PROVISIONER = "provisioner"
    EXPERIMENT_TASK = "experiment-task"
    RANGE_TASK = "range-task"


class BackendCapability(StrEnum):
    """A cloud-neutral capability protocol a backend can satisfy.

    These name the seams under ``shared.cloud`` and ``engine/provisioner/cloud`` that
    domain code already calls; a backend bundle *declares* which it provides, but it
    does not let domain code import provider packages directly.
    """

    STORAGE = "storage"
    QUEUE_CONSUMER = "queue-consumer"
    QUEUE_PUBLISHER = "queue-publisher"
    TASK_RUNNER = "task-runner"
    SECRETS = "secrets"
    CONFIG_STORE = "config-store"
    EVENT_BUS = "event-bus"
    DATABASE_AUTH = "database-auth"
    NETWORK_INVENTORY = "network-inventory"


class OutputKind(StrEnum):
    """The shape of a generated output."""

    RUNTIME_ENV = "runtime-env"
    TERRAFORM_VAR = "terraform-var"
    TERRAFORM_OUTPUT = "terraform-output"
    HELM_VALUE = "helm-value"
    K8S_ARTIFACT = "k8s-artifact"
    COMPAT_ALIAS = "compat-alias"


class OutputDestination(StrEnum):
    """Where a generated output is placed.

    Used together with :class:`OutputSensitivity` to keep secret *values* out of
    non-secret destinations: a ``SECRET_VALUE`` output may only land in a secret store.
    """

    RUNTIME_ENV = "runtime-env"  # process environment / Kubernetes ConfigMap / ECS task definition env
    # Placement labels — the SECRET_ prefix names *where* a value lands, not a credential.
    KUBERNETES_SECRET = "kubernetes-secret"  # noqa: S105 # nosec B105
    PROVIDER_SECRET_STORE = "provider-secret-store"  # noqa: S105 # nosec B105
    TERRAFORM_VARIABLES = "terraform-variables"
    HELM_VALUES = "helm-values"
    GENERATED_FILE = "generated-file"


#: Destinations a ``SECRET_VALUE`` output is allowed to be placed in.
_SECRET_VALUE_DESTINATIONS: frozenset[OutputDestination] = frozenset(
    {OutputDestination.KUBERNETES_SECRET, OutputDestination.PROVIDER_SECRET_STORE}
)


class _ContractModel(BaseModel):
    """Frozen, closed base for every contract type — registry data is immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_non_empty(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("must be a non-empty string with no surrounding whitespace")
    return value


def _check_repo_relative(value: str) -> str:
    _check_non_empty(value)
    if value.startswith("/"):
        raise ValueError(f"{value!r} must be a repository-relative path, not an absolute host path")
    if ".." in value.split("/"):
        raise ValueError(f"{value!r} must not contain a '..' path segment")
    return value


def _check_unique(values: Iterable[str], *, field: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"{field} has a duplicate entry {value!r}; each must be unique")
        seen.add(value)


# Pydantic error types whose ``msg`` is whatever string a custom validator raised — it
# could echo the rejected input, so it is replaced with a generic message (backend
# settings may carry sensitive references). Every other Pydantic error type's ``msg`` is
# generated from the type/context and is input-free.
_CUSTOM_VALIDATOR_ERROR_TYPES: frozenset[str] = frozenset({"value_error", "assertion_error"})


def _safe_pydantic_message(err: dict[str, Any]) -> str:
    if err["type"] in _CUSTOM_VALIDATOR_ERROR_TYPES:
        return "failed a backend-specific validation check"
    return err["msg"]


def _config_issues_from_validation_error(exc: ValidationError, *, prefix: str) -> list[ConfigIssue]:
    """Convert a Pydantic ``ValidationError`` to sanitized, path-anchored issues.

    Each issue carries only the prefixed location (e.g. ``settings.region``) and a message
    drawn from Pydantic's own type-derived text — falling back to a generic message for
    custom validator errors. The error's ``input`` value (which may be sensitive) is in
    the raw ``errors()`` records but is never read, so it cannot reach a :class:`ConfigIssue`.
    """
    return [
        ConfigIssue(prefix + "".join(f".{part}" for part in err["loc"]), _safe_pydantic_message(err))
        for err in exc.errors()
    ]


class CommandSpec(_ContractModel):
    """A backend check/renderer invocation, as an argv array (never a shell string)."""

    argv: tuple[str, ...]
    description: str

    @field_validator("argv")
    @classmethod
    def _check_argv(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("must be a non-empty argv array (the executable plus its arguments)")
        for index, arg in enumerate(v):
            if not isinstance(arg, str) or not arg or arg != arg.strip():
                raise ValueError(f"argv[{index}] must be a non-empty string with no surrounding whitespace")
            if any(ch.isspace() for ch in arg):
                raise ValueError(
                    f"argv[{index}] {arg!r} must not contain internal whitespace; "
                    "this is an argv array — each token is a separate element, not a shell string"
                )
            bad = "".join(sorted(set(arg) & _SHELL_METACHARACTERS))
            if bad:
                raise ValueError(
                    f"argv[{index}] {arg!r} contains shell metacharacters {bad!r}; "
                    "registry commands are argv arrays, not shell strings"
                )
            # Backend metadata must resolve to repo-owned entrypoints / argv specs, never
            # absolute host paths or path traversal — the executable is resolved on PATH
            # and any path argument is relative to the repository.
            if arg.startswith("/"):
                raise ValueError(
                    f"argv[{index}] {arg!r} must not be an absolute host path; "
                    "use a PATH-resolved executable and repository-relative path arguments"
                )
            if ".." in arg.split("/"):
                raise ValueError(f"argv[{index}] {arg!r} must not contain a '..' path segment")
        if not _EXECUTABLE_NAME_RE.match(v[0]):
            raise ValueError(
                f"argv[0] {v[0]!r} must be a bare executable name resolved on PATH "
                f"(matching {_EXECUTABLE_NAME_RE.pattern})"
            )
        return v


class RequiredTool(_ContractModel):
    """A command-line tool the backend's setup/deploy/doctor flow needs.

    ``name`` is the bare executable name a setup/doctor flow looks up on PATH (e.g.
    ``terraform``, ``uv``), so it is held to the same grammar as a command spec's
    ``argv[0]`` — not free-form text.
    """

    name: str
    purpose: str
    min_version: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _EXECUTABLE_NAME_RE.match(v):
            raise ValueError(f"tool name {v!r} must be a bare executable name matching {_EXECUTABLE_NAME_RE.pattern}")
        return v

    @field_validator("purpose")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class RequiredSecret(_ContractModel):
    """A secret the backend needs, declared by logical name and reference grammar.

    The root config holds *references* (a per-provider secret name, a GitHub Actions
    secret name, an env var, or ``prompt``), never values. ``reference_grammar`` is the
    human-readable description of what a valid reference looks like for this backend;
    ``reference_pattern`` is the optional machine-readable form — an anchored regex a
    consumer can match a supplied reference against. The provisional registry entries
    leave ``reference_pattern`` unset (no enforcement) until the backend supplies one,
    just like :attr:`BackendBundle.settings_model`.
    """

    logical_name: str
    purpose: str
    reference_grammar: str
    reference_pattern: str | None = None

    @field_validator("logical_name")
    @classmethod
    def _check_logical_name(cls, v: str) -> str:
        if not _SECRET_NAME_RE.match(v):
            raise ValueError(
                f"logical secret name {v!r} must match ^[a-z][a-z0-9_]*$ (the same grammar as RootConfig.secrets keys)"
            )
        return v

    @field_validator("purpose", "reference_grammar")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return _check_non_empty(v)

    @field_validator("reference_pattern")
    @classmethod
    def _check_reference_pattern(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v:
            raise ValueError("must be a non-empty regular expression, or omitted entirely")
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"is not a valid regular expression: {exc}") from exc
        return v

    def matches_reference(self, value: str) -> bool | None:
        """Whether ``value`` is a valid reference for this secret.

        ``prompt`` (:data:`PROMPT_REFERENCE`) is always accepted — it declares the secret
        while deferring the concrete reference to deploy time. Otherwise this returns
        ``None`` when the backend has not declared a ``reference_pattern`` (a consumer
        should fall back to the deploy-time provider check), or ``True`` / ``False`` from
        a full-string regex match.
        """
        if value == PROMPT_REFERENCE:
            return True
        if self.reference_pattern is None:
            return None
        return re.fullmatch(self.reference_pattern, value) is not None


class GeneratedOutput(_ContractModel):
    """A runtime/infrastructure/CI value a backend renderer produces.

    ``sensitivity`` and ``destination`` together keep secret *values* out of non-secret
    places: a ``SECRET_VALUE`` output may only be placed in a Kubernetes Secret or a
    provider secret store, never in a ConfigMap, Terraform variables, Helm values, a
    generated file, generated docs, a dry-run, or a plan comment.
    """

    name: str
    kind: OutputKind
    owner: str
    source: str
    destination: OutputDestination
    sensitivity: OutputSensitivity
    process_roles: tuple[ProcessRole, ...] = ()
    description: str

    @field_validator("name", "owner", "source", "description")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return _check_non_empty(v)

    @model_validator(mode="after")
    def _check_sensitivity_destination(self) -> GeneratedOutput:
        if self.sensitivity is OutputSensitivity.SECRET_VALUE and self.destination not in _SECRET_VALUE_DESTINATIONS:
            allowed = ", ".join(sorted(d.value for d in _SECRET_VALUE_DESTINATIONS))
            raise ValueError(
                f"a secret-value output must be placed in a secret store ({allowed}), not {self.destination.value!r}"
            )
        return self


class ValidationCheck(_ContractModel):
    """A check a backend runs (or front-runs) before mutating infrastructure."""

    name: str
    command: CommandSpec
    description: str
    blocking: bool = True

    @field_validator("name", "description")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class HealthCheck(_ContractModel):
    """A read-only post-render or post-deploy probe."""

    name: str
    target: str
    requires_credentials: bool
    timeout_seconds: int = Field(gt=0)
    description: str

    @field_validator("name", "target", "description")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class OwnedFiles(_ContractModel):
    """Repo-relative path roots a backend bundle owns, grouped by purpose.

    Validation and docs generation use these to find a backend's files without a branch
    router. Every entry must be repository-relative (no absolute host paths, no ``..``).
    """

    infrastructure: tuple[str, ...] = ()
    kubernetes: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    workflows: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()

    @field_validator("infrastructure", "kubernetes", "scripts", "workflows", "examples", "docs")
    @classmethod
    def _check_paths(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_check_repo_relative(path) for path in v)


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
    def _check_contract_version(cls, v: Any) -> int:
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

    def validate_settings(self, settings: Mapping[str, Any]) -> dict[str, Any]:
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

    def settings_issues(self, settings: Mapping[str, Any]) -> list[ConfigIssue]:
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

    def secret_reference_issues(self, secrets: Mapping[str, Any]) -> list[ConfigIssue]:
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
