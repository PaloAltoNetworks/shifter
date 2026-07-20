"""Command, tool, and secret contract specs.

``CommandSpec``, ``RequiredTool``, ``RequiredSecret``. Split out of the former
monolithic ``installation.contract`` module (#561) with behavior unchanged;
re-exported by :mod:`installation.contract` so the public import surface stays
identical.
"""

from __future__ import annotations

import re

from pydantic import field_validator

from ._base import _check_non_empty, _ContractModel, _validate_argv_token

# A bare executable name resolved on PATH (no path separators, no spaces): the argv[0] of
# a command spec and the name of a ``RequiredTool`` — e.g. ``terraform``, ``uv``,
# ``python3``. A consumer must be able to tell a structured argv from a shell fragment, so
# the executable element is held to this grammar rather than free-form text. ``\w`` is the
# ASCII word-character class here (``re.ASCII``), then word characters plus ``.`` / ``-``.
_EXECUTABLE_NAME_RE = re.compile(r"^\w[\w.-]*$", re.ASCII)
# A logical secret name — the same grammar as the keys of ``RootConfig.secrets`` — so a
# bundle's required secret can be matched against what the user supplied.
_SECRET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: The universal "supply this at deploy time" reference value: a ``secrets`` entry whose
#: value is ``prompt`` declares the secret without committing a concrete reference; it is
#: a valid reference for every backend regardless of that backend's ``reference_pattern``.
PROMPT_REFERENCE = "prompt"  # nosec B105 - the literal "prompt" sentinel, not a credential


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
            _validate_argv_token(index, arg)
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
