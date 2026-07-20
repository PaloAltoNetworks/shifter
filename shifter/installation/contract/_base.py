"""Shared contract base model and sanitized-validation helpers.

Split out of the former monolithic ``installation.contract`` module (#561) with
behavior unchanged; re-exported by :mod:`installation.contract` so the public
import surface stays identical.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from ..errors import ConfigIssue

# Characters that would let an argv element be (mis)interpreted as a shell fragment if
# anyone ever ``str.join``'d the argv array and handed it to a shell. Registry command
# specs are argv arrays executed *without* a shell; rejecting these (and any internal
# whitespace) keeps a shell fragment out of the registry data itself.
_SHELL_METACHARACTERS = frozenset(";&|`$<>\n\r")


class _ContractModel(BaseModel):
    """Frozen, closed base for every contract type — registry data is immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_non_empty(value: str) -> str:
    """Reject an empty string or one with leading/trailing whitespace."""
    if not value or value != value.strip():
        raise ValueError("must be a non-empty string with no surrounding whitespace")
    return value


def _check_repo_relative(value: str) -> str:
    """Reject an absolute host path or a path containing a '..' traversal segment."""
    _check_non_empty(value)
    if value.startswith("/"):
        raise ValueError(f"{value!r} must be a repository-relative path, not an absolute host path")
    if ".." in value.split("/"):
        raise ValueError(f"{value!r} must not contain a '..' path segment")
    return value


def _check_unique(values: Iterable[str], *, field: str) -> None:
    """Raise if ``values`` contains a duplicate entry."""
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


def _safe_pydantic_message(err: Mapping[str, Any]) -> str:
    """Return a sanitized message for a single Pydantic error record."""
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


def _validate_argv_token(index: int, arg: object) -> None:
    """Validate one argv token: non-empty string, no whitespace/metachars/abs-path/traversal."""
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
