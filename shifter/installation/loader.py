"""Load and fail-fast validate the root installation config (``shifter.yaml``).

:func:`load_root_config` is the entry point for code paths that need the parsed config
(setup, doctor, CI checks, runtime derivation): it returns a validated
:class:`~installation.schema.RootConfig` or raises
:class:`~installation.errors.InstallationConfigError` with *all* problems aggregated, so
a malformed root config (unknown/missing/conflicting key, bad backend, bad
deployment identity, duplicate YAML key, raw key material in ``secrets``, a
backend-specific ``settings`` problem, or a secret reference the selected backend
recognizes as malformed) is rejected before Terraform, Helm, Django startup, workers, or
deployment scripts run. It first validates the root *shape* (:mod:`installation.schema`),
then runs the selected backend bundle's ``settings`` and secret-reference checks
(:mod:`installation.registry` / :mod:`installation.contract`).
:func:`validate_root_config_file` is the non-raising variant for "check, then report"
callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from . import range_egress, registry
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
    """Read the YAML file at ``path`` and return the parsed top-level mapping.

    Raises :class:`InstallationConfigError` when the file is missing,
    unreadable, syntactically invalid, empty, or not a mapping at the top
    level. Duplicate / merge keys are rejected during a parse-to-node-graph
    pre-pass so PyYAML's silent last-wins behavior cannot validate a config
    the operator did not author.
    """
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
    """Convert a YAML parse error to a sanitized :class:`ConfigIssue`.

    The message is composed strictly from the parser's own problem description
    and position so a parse error on a line that holds a value (for example a
    mistyped secret) cannot be echoed back through the error surface.
    """
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
    """Convert a Pydantic ``ValidationError`` to sorted, deduplicated issues.

    Each issue carries the dotted location of the offending key (or ``<root>``)
    and Pydantic's type-derived message. The input value is never read, so a
    rejected secret reference cannot leak through this conversion. Returned
    issues are sorted by ``(path, message)`` so renderings are stable.
    """
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


def _backend_issues_from_raw(data: dict[str, Any]) -> list[ConfigIssue]:
    """Best-effort backend checks against the raw parsed mapping, used when the root
    schema already failed: if the ``backend`` is recognized and ``settings`` / ``secrets``
    are mappings, surface the selected bundle's problems so the user sees everything at
    once. Returns ``[]`` when the backend cannot be determined."""
    backend = data.get("backend")
    if not isinstance(backend, str):
        return []
    bundle = registry.get_backend_bundle(backend)
    if bundle is None:
        return []
    issues: list[ConfigIssue] = []
    settings = data.get("settings", {})
    if isinstance(settings, dict):
        issues.extend(bundle.settings_issues(settings))
        # range_egress (PLAT-220) is cross-backend; the bundle-specific check above
        # may pass-through a settings_model=None backend without inspecting it.
        _, range_egress_issues = range_egress.validate_settings_block(settings)
        issues.extend(range_egress_issues)
    secrets = data.get("secrets", {})
    if isinstance(secrets, dict):
        issues.extend(bundle.secret_reference_issues(secrets))
    return issues


def load_root_config(path: str | Path) -> RootConfig:
    """Parse and validate a root installation config file.

    Raises:
        InstallationConfigError: if the file is missing, unparseable, fails the root
            schema, or fails the selected backend bundle's ``settings`` / secret-reference
            checks. All problems — root-shape and backend-specific — are aggregated on the
            exception's ``issues``.
    """
    config_path = Path(path)
    data = _read_yaml_mapping(config_path)
    try:
        config = RootConfig.model_validate(data)
    except ValidationError as exc:
        issues = _issues_from_validation_error(exc)
        issues.extend(_backend_issues_from_raw(data))
        raise InstallationConfigError(issues) from exc

    # The root schema validated the *shape*; the selected backend bundle owns the
    # contents of ``settings`` and the per-provider secret reference grammar.
    bundle = registry.get_backend_bundle(config.backend)
    if bundle is None:  # pragma: no cover - an unknown backend already failed the root schema
        return config
    try:
        normalized_settings = bundle.validate_settings(config.settings)
    except InstallationConfigError as exc:
        # Aggregate the settings *and* secret-reference problems before raising.
        raise InstallationConfigError([*exc.issues, *bundle.secret_reference_issues(config.secrets)]) from exc
    # Cross-backend settings validation (PLAT-220 range_egress). Lives in the loader
    # because the policy shape applies identically to AWS and GCP; per-backend
    # settings_model migrations (#1116 / #1117) may later move this onto the model.
    normalized_settings, range_egress_issues = range_egress.validate_settings_block(normalized_settings)
    if range_egress_issues:
        raise InstallationConfigError([*range_egress_issues, *bundle.secret_reference_issues(config.secrets)])
    secret_issues = bundle.secret_reference_issues(config.secrets)
    if secret_issues:
        raise InstallationConfigError(secret_issues)
    # Store the bundle's normalized settings (defaults, coercions) so callers of
    # ``load_root_config`` see the same parsed shape the backend uses; for a bundle with
    # no ``settings_model`` this is a shallow copy of the user's mapping.
    config.settings = normalized_settings
    return config


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
