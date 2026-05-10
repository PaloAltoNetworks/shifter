"""Load and fail-fast validate the root installation config (``shifter.yaml``).

:func:`load_root_config` is the entry point for code paths that need the parsed config
(setup, doctor, CI checks, runtime derivation): it returns a validated
:class:`~installation.schema.RootConfig` or raises
:class:`~installation.errors.InstallationConfigError` with *all* problems aggregated, so
a malformed root config (unknown/missing/conflicting key, bad backend, bad
deployment identity, duplicate YAML key, raw key material in ``secrets``) is rejected
before Terraform, Helm, Django startup, workers, or deployment scripts run. This is
root-config *shape* validation; the contents of ``settings`` and the per-backend
required-settings set are validated by the selected backend bundle's contract (#1113).
:func:`validate_root_config_file` is the non-raising variant for "check, then report"
callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import ConfigIssue, InstallationConfigError
from .schema import RootConfig

_YAML_MERGE_TAG = "tag:yaml.org,2002:merge"


def _check_mapping_key(key_node: yaml.Node, value_node: yaml.Node, seen: set[object]) -> None:
    """Reject a ``<<`` merge key or a key already present in ``seen``; otherwise record it.

    Raises a :class:`yaml.constructor.ConstructorError` (a :class:`yaml.YAMLError`) with the
    offending key's position so the loader can report it like any other parse error.
    """
    is_merge = getattr(key_node, "tag", "") == _YAML_MERGE_TAG or (
        isinstance(key_node, yaml.ScalarNode) and key_node.value == "<<"
    )
    if is_merge:
        raise yaml.constructor.ConstructorError(
            "while constructing a mapping",
            value_node.start_mark,
            "YAML merge keys ('<<') are not supported in the root installation config",
            key_node.start_mark,
        )
    key = key_node.value if isinstance(key_node, yaml.ScalarNode) else repr(key_node.value)
    if key in seen:
        raise yaml.constructor.ConstructorError(
            "while constructing a mapping",
            value_node.start_mark,
            f"found duplicate key {key!r}",
            key_node.start_mark,
        )
    seen.add(key)


def _reject_duplicate_keys(node: yaml.Node, _visited: set[int] | None = None) -> None:
    """Walk a parsed YAML node graph and reject duplicated mapping keys and merge keys.

    PyYAML's loader silently keeps the *last* value for a duplicated key, so
    ``backend: aws`` followed by ``backend: gcp`` would validate as ``gcp`` without
    complaint — a confident, wrong "OK" for the authoritative root config. YAML merge
    keys (``<<``) are rejected outright: they too let a "merged" key and an explicit
    key of the same name coexist (the explicit one silently wins after construction),
    and they add nothing to a hand-authored installation config. Both checks run on the
    parsed node graph before any value is constructed. ``_visited`` guards against
    recursive alias graphs (``&a {b: *a}``) so a crafted config cannot cause unbounded
    recursion.
    """
    if _visited is None:
        _visited = set()
    if id(node) in _visited:
        return
    _visited.add(id(node))
    if isinstance(node, yaml.MappingNode):
        seen: set[object] = set()
        for key_node, value_node in node.value:
            _check_mapping_key(key_node, value_node, seen)
            _reject_duplicate_keys(value_node, _visited)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _reject_duplicate_keys(item, _visited)


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InstallationConfigError(
            [
                ConfigIssue(
                    str(path),
                    "root installation config not found",
                    "create it from one of the examples in shifter/installation/examples/",
                )
            ]
        ) from exc
    except OSError as exc:
        detail = getattr(exc, "strerror", None) or str(exc)
        raise InstallationConfigError(
            [ConfigIssue(str(path), f"could not read root installation config: {detail}")]
        ) from exc

    try:
        # Parse to a node graph first (no Python objects constructed) so duplicate
        # mapping keys can be rejected before SafeLoader silently collapses them.
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        if node is not None:
            _reject_duplicate_keys(node)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise InstallationConfigError([_yaml_issue(path, exc)]) from exc

    if data is None:
        raise InstallationConfigError(
            [ConfigIssue(str(path), "root installation config is empty; expected a YAML mapping at the top level")]
        )
    if not isinstance(data, dict):
        raise InstallationConfigError(
            [ConfigIssue(str(path), f"expected a YAML mapping at the top level, found {type(data).__name__}")]
        )
    return data


def _yaml_issue(path: Path, exc: yaml.YAMLError) -> ConfigIssue:
    # Build the message from the parser's own problem description and position only —
    # never from the file content — so a parse error on a line that holds a value
    # (for example a mistyped secret) cannot be echoed back through the error surface.
    where = ""
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if mark is not None:
        where = f" at line {mark.line + 1}, column {mark.column + 1}"
    problem = getattr(exc, "problem", None) or getattr(exc, "context", None) or "could not parse YAML"
    return ConfigIssue(str(path), f"invalid YAML{where}: {problem}")


def _issues_from_validation_error(exc: ValidationError) -> list[ConfigIssue]:
    seen: set[tuple[str, str]] = set()
    issues: list[ConfigIssue] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        path = ".".join(str(part) for part in loc) if loc else "<root>"
        message = err.get("msg", "invalid value")
        dedup_key = (path, message)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        issues.append(ConfigIssue(path, message))
    issues.sort(key=lambda issue: (issue.path, issue.message))
    return issues


def load_root_config(path: str | Path) -> RootConfig:
    """Parse and validate a root installation config file.

    Raises:
        InstallationConfigError: if the file is missing, unparseable, or fails schema
            validation. All problems are aggregated on the exception's ``issues``.
    """
    config_path = Path(path)
    data = _read_yaml_mapping(config_path)
    try:
        return RootConfig.model_validate(data)
    except ValidationError as exc:
        raise InstallationConfigError(_issues_from_validation_error(exc)) from exc


def validate_root_config_file(path: str | Path) -> list[ConfigIssue]:
    """Validate a root installation config file, returning the problems found.

    Returns an empty list when the config is valid. Never raises
    :class:`InstallationConfigError`.
    """
    try:
        load_root_config(path)
    except InstallationConfigError as exc:
        return list(exc.issues)
    return []
