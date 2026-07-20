"""Generated-output and check contract models.

``GeneratedOutput``, ``ValidationCheck``, ``HealthCheck``, ``OwnedFiles``. Split out
of the former monolithic ``installation.contract`` module (#561) with behavior
unchanged; re-exported by :mod:`installation.contract` so the public import surface
stays identical.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from ._base import _check_non_empty, _check_repo_relative, _ContractModel
from ._enums import _SECRET_VALUE_DESTINATIONS, OutputDestination, OutputKind, OutputSensitivity, ProcessRole
from ._specs import CommandSpec


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
