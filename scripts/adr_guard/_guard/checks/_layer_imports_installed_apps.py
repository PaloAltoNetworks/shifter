"""INSTALLED_APPS classification check (ADR-001-R3).

Split out of ``layer_imports.py`` to keep each module under the file-length
limit; every public name here is re-imported by that module so the package
surface is unchanged.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from .._common import (
    Violation,
)
from ._layer_imports_policy import load_classification


_PLATFORM_REL = "shifter/shifter_platform"
_SETTINGS_REL = "shifter/shifter_platform/config/settings.py"
_LAYER_POLICY_REL = "scripts/check_layer_imports/layer_imports.yaml"
_INSTALLED_APPS = "INSTALLED_APPS"
# List mutations whose resulting entries the AST pass cannot resolve; each one
# makes the check fail closed rather than silently skipping the entry.
_OPAQUE_INSTALLED_APPS_METHODS = frozenset({"extend", "insert", "__iadd__", "__add__"})


def _classified_packages(repo_root: Path) -> set[str]:
    """Return the union of every canonically classified first-party package."""
    classification = load_classification(repo_root / _LAYER_POLICY_REL)
    return {pkg for packages in classification.values() for pkg in packages}


def _local_appconfig_packages(repo_root: Path) -> set[str]:
    """Return local packages under shifter_platform whose apps.py defines an AppConfig.

    A tracked local Django app is a top-level package with an ``apps.py`` that
    subclasses ``AppConfig``. Directories without an AppConfig (e.g. the retired
    ``documentation`` package, ADR-038) are not tracked apps and are excluded.
    """
    platform = repo_root / _PLATFORM_REL
    found: set[str] = set()
    for apps_py in platform.glob("*/apps.py"):
        try:
            text = apps_py.read_text(encoding="utf-8")
        except OSError:
            continue
        if re.search(r"class\s+\w+\s*\(\s*[\w.]*AppConfig\b", text):
            found.add(apps_py.parent.name)
    return found


def _sequence_entries(value: ast.expr, dynamic_detail: str) -> tuple[list[str], list[str]]:
    """Split a list/tuple literal into (string-literal elements, unresolved reprs).

    A value that is not a list/tuple literal at all yields ``dynamic_detail`` as
    the single unresolved reason.
    """
    if not isinstance(value, (ast.List, ast.Tuple)):
        return [], [dynamic_detail]
    resolved: list[str] = []
    unresolved: list[str] = []
    for elt in value.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            resolved.append(elt.value)
        else:
            unresolved.append("non-literal INSTALLED_APPS entry")
    return resolved, unresolved


def _targets_installed_apps(node: ast.Assign) -> bool:
    """True when an assignment statement writes to ``INSTALLED_APPS``."""
    return any(isinstance(target, ast.Name) and target.id == _INSTALLED_APPS for target in node.targets)


def _is_installed_apps_add(node: ast.AugAssign) -> bool:
    """True for an ``INSTALLED_APPS += ...`` augmented assignment."""
    target = node.target
    return isinstance(target, ast.Name) and target.id == _INSTALLED_APPS and isinstance(node.op, ast.Add)


def _is_installed_apps_attribute(func: ast.expr) -> bool:
    """True for an ``INSTALLED_APPS.<attr>`` call target."""
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == _INSTALLED_APPS
    )


def _installed_apps_append_entries(node: ast.Call) -> tuple[list[str], list[str]]:
    """Resolve ``INSTALLED_APPS.append(...)`` into (entries, unresolved reprs)."""
    arg = node.args[0] if node.args else None
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [arg.value], []
    return [], ["non-literal INSTALLED_APPS.append() argument"]


def _installed_apps_call_entries(node: ast.Call) -> tuple[list[str], list[str]]:
    """Resolve an ``INSTALLED_APPS.<method>(...)`` mutation into (entries, unresolved reprs).

    Calls that do not target ``INSTALLED_APPS`` contribute nothing.
    """
    func = node.func
    if _is_installed_apps_attribute(func):
        if func.attr == "append":
            return _installed_apps_append_entries(node)
        if func.attr in _OPAQUE_INSTALLED_APPS_METHODS:
            return [], [f"unresolvable INSTALLED_APPS.{func.attr}() mutation"]
    return [], []


def _parse_installed_apps(settings_text: str) -> tuple[list[str], list[str]]:
    """Return (resolved app strings, unresolved dynamic reprs) from INSTALLED_APPS.

    Parses the ``INSTALLED_APPS = [...]`` literal plus ``INSTALLED_APPS.append(...)``
    calls. Any entry that is not a string constant — a dynamic expression, or an
    ``extend``/``insert`` mutation — is returned as unresolved so the check fails
    closed rather than silently skipping it.
    """
    resolved: list[str] = []
    unresolved: list[str] = []

    for node in ast.walk(ast.parse(settings_text)):
        if isinstance(node, ast.Assign) and _targets_installed_apps(node):
            entries, problems = _sequence_entries(node.value, "INSTALLED_APPS not assigned a list/tuple literal")
        elif isinstance(node, ast.AugAssign) and _is_installed_apps_add(node):
            # INSTALLED_APPS += [...] / += SOME_APPS
            entries, problems = _sequence_entries(node.value, "unresolvable INSTALLED_APPS += mutation")
        elif isinstance(node, ast.Call):
            entries, problems = _installed_apps_call_entries(node)
        else:
            continue
        resolved.extend(entries)
        unresolved.extend(problems)
    return resolved, unresolved


def check_installed_apps_classified(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Fail closed when a first-party INSTALLED_APPS app is unclassified (#1523).

    Enforces set-equality between the canonical classification
    (layer_imports.yaml), the tracked local AppConfig packages, and the
    first-party apps actually installed. Adding a local app to INSTALLED_APPS
    without classifying it, leaving a stale classification entry, or introducing
    a dynamic INSTALLED_APPS entry the checker cannot resolve, all fail closed.
    """
    # whole-tree invariant; not file-scoped
    del files
    settings_path = repo_root / _SETTINGS_REL
    policy_path = repo_root / _LAYER_POLICY_REL
    if not settings_path.exists() or not policy_path.exists():
        return []

    violations: list[Violation] = []
    classified = _classified_packages(repo_root)
    local_apps = _local_appconfig_packages(repo_root)
    installed, unresolved = _parse_installed_apps(settings_path.read_text(encoding="utf-8"))

    for detail in unresolved:
        violations.append(
            Violation(
                "installed-apps-classified",
                "ADR-001-R3",
                _SETTINGS_REL,
                f"INSTALLED_APPS has an entry the classifier cannot resolve ({detail}); "
                "use a string literal so first-party apps stay classifiable",
            )
        )

    installed_first_party = {entry.split(".")[0] for entry in installed} & local_apps

    for pkg in sorted(installed_first_party - classified):
        violations.append(
            Violation(
                "installed-apps-classified",
                "ADR-001-R3",
                _SETTINGS_REL,
                f"first-party app '{pkg}' is in INSTALLED_APPS but not classified in {_LAYER_POLICY_REL}",
            )
        )
    for pkg in sorted(local_apps - classified):
        violations.append(
            Violation(
                "installed-apps-classified",
                "ADR-001-R3",
                _LAYER_POLICY_REL,
                f"local app '{pkg}' has an AppConfig but is not classified in {_LAYER_POLICY_REL}",
            )
        )
    for pkg in sorted(classified - local_apps):
        violations.append(
            Violation(
                "installed-apps-classified",
                "ADR-001-R3",
                _LAYER_POLICY_REL,
                f"classified package '{pkg}' has no local AppConfig under {_PLATFORM_REL} (stale classification)",
            )
        )

    return violations


__all__ = [
    "_INSTALLED_APPS",
    "_LAYER_POLICY_REL",
    "_OPAQUE_INSTALLED_APPS_METHODS",
    "_PLATFORM_REL",
    "_SETTINGS_REL",
    "_classified_packages",
    "_installed_apps_append_entries",
    "_installed_apps_call_entries",
    "_is_installed_apps_add",
    "_is_installed_apps_attribute",
    "_local_appconfig_packages",
    "_parse_installed_apps",
    "_sequence_entries",
    "_targets_installed_apps",
    "check_installed_apps_classified",
]
