#!/usr/bin/env python3
"""Repo-native ADR enforcement checks."""

from __future__ import annotations

import argparse
import ast
import glob
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Every first-party Django app is classified (ADR-001, #1523). Held to
# set-equality with the canonical classification in layer_imports.yaml by the
# layer-classification-parity check.
LAYERS = ("shared", "engine", "cms", "management", "mission_control", "ctf", "config", "risk_register")
IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+"
    r"((?:shared|engine|cms|management|mission_control|ctf|config|risk_register)(?:\.\w+)*)",
    re.MULTILINE,
)
CYBERSCRIPT_IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+(cyberscript(?:\.\w+)*)",
    re.MULTILINE,
)
CYBERSCRIPT_ALLOWED_LAYER = "shared"
REQUIRED_ADR_KEYS = {
    "id",
    "title",
    "status",
    "scope",
    "decision",
    "rules",
    "exceptions",
    "enforcement",
    "evidence",
}
REQUIRED_EXCEPTION_KEYS = {"rule_id", "owner", "reason", "expires_on"}
REQUIRED_INTERFACE_CONTRACTS = {"ADR-039": "range-substrate/v1"}
RANGE_SUBSTRATE_OPERATIONS = frozenset({"provision", "destroy", "pause", "resume"})
RANGE_SUBSTRATE_RESOURCES = frozenset({"network", "instance", "ngfw", "remote-access"})
RANGE_SUBSTRATE_INITIAL_ADAPTERS = frozenset({"aws-terraform", "gcp-gdc"})
RANGE_SUBSTRATE_DEFERRED_ADAPTERS = frozenset({"azure"})
RANGE_SUBSTRATE_ISSUE_REFERENCES = frozenset({"283", "478", "265", "277"})
GUARDRAIL_PREFIXES = (
    ".github/workflows/",
    ".claude/hooks/",
    "scripts/adr_guard/",
    "docs/adr/",
)
GUARDRAIL_FILES = {
    ".pre-commit-config.yaml",
    ".ground-control.yaml",
    ".gc/plan-rules.md",
    ".claude/settings.json",
    "AGENTS.md",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/copilot-instructions.md",
    ".github/dependabot.yml",
    ".importlinter",
    ".tflint.hcl",
    ".gitleaks.toml",
    ".kube-linter.yaml",
    # Repo-root runtime config seeded by #777 (mcp_ops policy). Changes
    # here can weaken capability classes, profile gating, env defaults,
    # audit redaction, or prod-confirm policy without touching code, so
    # ADR enforcement watches the file.
    ".shifter.yaml",
    ".cursor/cli.json",
}
DOC_PATHS = (
    "docs/adr/",
    "docs/technical/dev/adr-enforcement.md",
    "docs/technical/dev/index.md",
    "docs/technical/index.md",
)


@dataclass(frozen=True)
class Violation:
    """A single ADR guard violation."""

    check: str
    rule_id: str
    path: str
    message: str


@dataclass(frozen=True)
class _BoundaryPatchSite:
    """One statically discovered mock patch target."""

    path: str
    line: int
    target: str


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _normalize_files(files: list[str] | None, repo_root: Path) -> list[str] | None:
    if files is None:
        return None

    normalized: list[str] = []
    for item in files:
        if not item:
            continue
        path = Path(item)
        if path.is_absolute():
            normalized.append(_repo_relative(path, repo_root))
        else:
            normalized.append(Path(item).as_posix().lstrip("./"))

    return sorted(set(normalized))


def _load_json_yaml(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_adr_registry(repo_root: Path) -> list[dict]:
    """Load and validate the ADR registry shape."""
    path = repo_root / "docs" / "adr" / "index.yaml"
    data = _load_json_yaml(path)
    if not isinstance(data, list):
        raise ValueError("docs/adr/index.yaml must contain a top-level list")
    return data


def load_adr_exceptions(repo_root: Path) -> list[dict]:
    """Load and validate the exception registry shape."""
    path = repo_root / "docs" / "adr" / "exceptions.yaml"
    data = _load_json_yaml(path)
    if not isinstance(data, list):
        raise ValueError("docs/adr/exceptions.yaml must contain a top-level list")
    return data


def validate_adr_exceptions(exceptions: list[dict]) -> list[str]:
    """Validate exception schema and expiry dates."""
    errors: list[str] = []
    for index, exception in enumerate(exceptions):
        missing = REQUIRED_EXCEPTION_KEYS - set(exception)
        if missing:
            errors.append(f"Exception entry {index} is missing keys: {sorted(missing)}")
            continue

        try:
            expires_on = _parse_iso_date(exception["expires_on"])
        except ValueError:
            errors.append(f"Exception entry {index} has invalid expires_on date: {exception['expires_on']!r}")
            continue

        if expires_on < date.today():
            errors.append(f"Exception entry {index} for {exception['rule_id']} expired on {exception['expires_on']}")

        paths = exception.get("paths", [])
        if paths and not isinstance(paths, list):
            errors.append(f"Exception entry {index} paths must be a list when present")

        checks = exception.get("checks", [])
        if checks and not isinstance(checks, list):
            errors.append(f"Exception entry {index} checks must be a list when present")

    return errors


def exception_matches(violation: Violation, exception: dict) -> bool:
    """Return True if an exception covers a given violation."""
    if exception.get("rule_id") != violation.rule_id:
        return False

    checks = exception.get("checks") or []
    if checks and violation.check not in checks:
        return False

    paths = exception.get("paths") or []
    if not paths:
        return True

    return any(fnmatch(violation.path, pattern) for pattern in paths)


def filter_excepted_violations(violations: list[Violation], exceptions: list[dict]) -> list[Violation]:
    """Drop violations that are covered by a non-expired exception."""
    filtered: list[Violation] = []
    for violation in violations:
        if any(exception_matches(violation, exception) for exception in exceptions):
            continue
        filtered.append(violation)
    return filtered


def _iter_yaml_section(config_path: Path, section: str) -> "list[tuple[str, list[str]]]":
    """Parse one top-level ``section:`` of the layer-policy YAML.

    Minimal, dependency-free reader for the two-level shape used by
    layer_imports.yaml (``section:`` -> ``key:`` -> ``- item`` list). Only the
    requested top-level section is parsed; other sections are ignored, so the
    ``classification`` and ``allowed`` blocks never bleed into each other.
    """
    result: dict[str, list[str]] = {}
    current_section: str | None = None
    current_key: str | None = None

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if indent == 0 and stripped.endswith(":"):
            current_section = stripped[:-1]
            current_key = None
            continue
        if current_section != section:
            continue
        if indent == 2 and stripped.endswith(":"):
            current_key = stripped[:-1]
            result[current_key] = []
            continue
        if current_key is not None and indent >= 4 and stripped.startswith("- "):
            result[current_key].append(stripped[2:].strip())

    return list(result.items())


def load_allowed_imports(config_path: Path) -> dict[str, list[str]]:
    """Load the simple layer import policy without external YAML dependencies."""
    return dict(_iter_yaml_section(config_path, "allowed"))


def load_allowed_symbols(config_path: Path) -> dict[str, dict[str, list[str]]]:
    """Parse the 3-level ``allowed_symbols:`` block (layer -> facade -> [symbols]).

    Dependency-free reader mirroring ``_iter_yaml_section`` one level deeper, for
    the per-symbol facade allowlists (ADR-001-R4). Only the ``allowed_symbols``
    top-level section is parsed; other sections are ignored.
    """
    result: dict[str, dict[str, list[str]]] = {}
    in_section = False
    current_layer: str | None = None
    current_facade: str | None = None

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if indent == 0 and stripped.endswith(":"):
            in_section = stripped[:-1] == "allowed_symbols"
            current_layer = None
            current_facade = None
            continue
        if not in_section:
            continue
        if indent == 2 and stripped.endswith(":"):
            current_layer = stripped[:-1]
            result[current_layer] = {}
            current_facade = None
            continue
        if indent == 4 and stripped.endswith(":") and current_layer is not None:
            current_facade = stripped[:-1]
            result[current_layer][current_facade] = []
            continue
        if current_layer is not None and current_facade is not None and indent >= 6 and stripped.startswith("- "):
            result[current_layer][current_facade].append(stripped[2:].strip())

    return result


def load_classification(config_path: Path) -> dict[str, list[str]]:
    """Load the canonical package classification without external YAML deps."""
    return dict(_iter_yaml_section(config_path, "classification"))


def is_import_allowed(from_layer: str, module_path: str, allowed: dict[str, list[str]]) -> bool:
    """Check whether an import is allowed by the layer policy.

    A dotted entry (e.g. ``cms.services``) is the public facade: the exact
    facade and its public submodules are allowed, but a private split-package
    submodule — any path component after the facade that starts with ``_``
    (``cms.services._range_pause``) — is not a cross-layer seam (ADR-001-R1).
    ``shared`` is the contracts layer and stays freely importable.
    """
    for entry in allowed.get(from_layer, []):
        if entry == "shared":
            if module_path == "shared" or module_path.startswith("shared."):
                return True
        elif "." in entry:
            if module_path == entry:
                return True
            if module_path.startswith(entry + "."):
                remainder = module_path[len(entry) + 1 :]
                if not any(part.startswith("_") for part in remainder.split(".")):
                    return True
        elif module_path == entry:
            return True
    return False


def iter_layer_files(repo_root: Path, files: list[str] | None) -> list[tuple[str, str]]:
    """Return repo-relative Python files grouped by originating layer."""
    candidates: list[Path]
    if files is None:
        candidates = list((repo_root / "shifter" / "shifter_platform").rglob("*.py"))
    else:
        candidates = [repo_root / rel for rel in files if rel.endswith(".py")]

    layer_files: list[tuple[str, str]] = []
    for path in candidates:
        if not path.exists():
            continue
        rel = _repo_relative(path, repo_root)
        parts = Path(rel).parts
        if len(parts) < 4:
            continue
        if parts[0:2] != ("shifter", "shifter_platform"):
            continue
        layer = parts[2]
        if layer in LAYERS:
            layer_files.append((rel, layer))

    return sorted(set(layer_files))


def get_changed_files(repo_root: Path) -> list[str]:
    """Get staged files, falling back to the current working tree diff."""
    commands = (
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "HEAD"],
    )

    for cmd in commands:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if files:
                return sorted(set(files))

    return []


def _registry_violation(path: str, message: str) -> Violation:
    """Shorthand: build an adr-registry / ADR-REGISTRY Violation at `path`."""
    return Violation("adr-registry", "ADR-REGISTRY", path, message)


def _validate_exact_string_members(
    value: object,
    expected: frozenset[str],
    field: str,
) -> list[str]:
    """Validate one closed interface-contract string collection."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [f"{field} must be a list of strings"]
    if len(value) != len(set(value)):
        return [f"{field} must not contain duplicates"]
    actual = set(value)
    if actual != expected:
        return [
            f"{field} must contain exactly {sorted(expected)}; got {sorted(actual)}"
        ]
    return []


def validate_interface_contract(contract: object, adr_id: str) -> list[str]:
    """Validate executable invariants declared by a typed ADR interface contract."""
    if not isinstance(contract, dict):
        return [f"{adr_id} interface_contract must be an object"]

    expected_kind = REQUIRED_INTERFACE_CONTRACTS.get(adr_id)
    kind = contract.get("kind")
    if expected_kind is not None and kind != expected_kind:
        return [f"{adr_id} interface_contract kind must be {expected_kind!r}"]
    if kind != "range-substrate/v1":
        return [f"{adr_id} interface_contract has unsupported kind {kind!r}"]

    errors: list[str] = []
    errors.extend(
        _validate_exact_string_members(
            contract.get("operations"),
            RANGE_SUBSTRATE_OPERATIONS,
            f"{adr_id} interface_contract.operations",
        )
    )
    errors.extend(
        _validate_exact_string_members(
            contract.get("resources"),
            RANGE_SUBSTRATE_RESOURCES,
            f"{adr_id} interface_contract.resources",
        )
    )

    conformance = contract.get("conformance")
    if not isinstance(conformance, dict):
        errors.append(f"{adr_id} interface_contract.conformance must be an object")
    else:
        for obligation in ("shared_black_box_suite", "real_provider_promotion_evidence"):
            if conformance.get(obligation) is not True:
                errors.append(
                    f"{adr_id} interface_contract.conformance.{obligation} must be true"
                )

    adapters = contract.get("adapters")
    if not isinstance(adapters, dict):
        errors.append(f"{adr_id} interface_contract.adapters must be an object")
    else:
        errors.extend(
            _validate_exact_string_members(
                adapters.get("initial"),
                RANGE_SUBSTRATE_INITIAL_ADAPTERS,
                f"{adr_id} interface_contract.adapters.initial",
            )
        )
        errors.extend(
            _validate_exact_string_members(
                adapters.get("deferred"),
                RANGE_SUBSTRATE_DEFERRED_ADAPTERS,
                f"{adr_id} interface_contract.adapters.deferred",
            )
        )

    references = contract.get("issue_references")
    if not isinstance(references, dict):
        errors.append(f"{adr_id} interface_contract.issue_references must be an object")
        return errors
    actual_references = set(references)
    if actual_references != RANGE_SUBSTRATE_ISSUE_REFERENCES:
        errors.append(
            f"{adr_id} interface_contract.issue_references must contain exactly "
            f"{sorted(RANGE_SUBSTRATE_ISSUE_REFERENCES)}; got {sorted(actual_references)}"
        )
    for reference, mapping in references.items():
        if not isinstance(mapping, dict):
            errors.append(f"{adr_id} issue reference {reference} mapping must be an object")
            continue
        mapping_fields = set(mapping)
        if mapping_fields == {"disposition"} and mapping["disposition"] == "out-of-scope":
            continue
        operations = mapping.get("operations")
        if (
            mapping_fields != {"operations"}
            or not isinstance(operations, list)
            or not operations
            or not all(isinstance(operation, str) for operation in operations)
            or not set(operations).issubset(RANGE_SUBSTRATE_OPERATIONS)
            or len(operations) != len(set(operations))
        ):
            errors.append(
                f"{adr_id} issue reference {reference} must exclusively map to a "
                "non-empty, duplicate-free list of declared operations or have only "
                "disposition 'out-of-scope'"
            )
    return errors


def _check_adr_entry(
    entry: dict,
    adr_ids: set[str],
    rule_ids: set[str],
    violations: list[Violation],
) -> None:
    """Validate one registry entry; append any per-entry violations.

    Also mutates `adr_ids` / `rule_ids` with the names this entry contributes
    so later entries can detect duplicates.
    """
    missing = REQUIRED_ADR_KEYS - set(entry)
    if missing:
        violations.append(
            _registry_violation(
                "docs/adr/index.yaml",
                f"ADR entry {entry.get('id', '<missing-id>')} is missing keys: {sorted(missing)}",
            )
        )
        return

    adr_id = entry["id"]
    if adr_id in adr_ids:
        violations.append(_registry_violation("docs/adr/index.yaml", f"Duplicate ADR id: {adr_id}"))
    adr_ids.add(adr_id)

    interface_contract = entry.get("interface_contract")
    if adr_id in REQUIRED_INTERFACE_CONTRACTS and interface_contract is None:
        violations.append(
            _registry_violation(
                "docs/adr/index.yaml",
                f"{adr_id} must define interface_contract kind "
                f"{REQUIRED_INTERFACE_CONTRACTS[adr_id]!r}",
            )
        )
    elif interface_contract is not None:
        for error in validate_interface_contract(interface_contract, adr_id):
            violations.append(_registry_violation("docs/adr/index.yaml", error))

    rules = entry.get("rules", [])
    if not isinstance(rules, list):
        violations.append(
            _registry_violation("docs/adr/index.yaml", f"{adr_id} rules must be a list")
        )
        return

    for rule in rules:
        rule_id = rule.get("id")
        if not rule_id:
            violations.append(
                _registry_violation(
                    "docs/adr/index.yaml", f"{adr_id} has a rule without an id"
                )
            )
            continue
        if rule_id in rule_ids:
            violations.append(
                _registry_violation("docs/adr/index.yaml", f"Duplicate rule id: {rule_id}")
            )
        rule_ids.add(rule_id)


def check_adr_registry(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Validate the ADR registry and exception references."""
    violations: list[Violation] = []

    try:
        registry = load_adr_registry(repo_root)
        exceptions = load_adr_exceptions(repo_root)
    except (OSError, ValueError, json.JSONDecodeError) as err:
        return [Violation("adr-registry", "ADR-REGISTRY", "docs/adr", str(err))]

    for error in validate_adr_exceptions(exceptions):
        violations.append(_registry_violation("docs/adr/exceptions.yaml", error))

    adr_ids: set[str] = set()
    rule_ids: set[str] = set()
    for entry in registry:
        _check_adr_entry(entry, adr_ids, rule_ids, violations)

    for exception in exceptions:
        rule_id = exception.get("rule_id")
        if not rule_id or rule_id not in rule_ids:
            violations.append(
                _registry_violation(
                    "docs/adr/exceptions.yaml",
                    f"Exception references unknown rule id: {rule_id!r}",
                )
            )

    return violations


def iter_private_facade_imports(text: str) -> set[str]:
    """Return ``layer.path._private`` targets imported via ``from ... import``.

    The ``IMPORT_PATTERN`` regex only captures the module path, so
    ``from cms.services import _range_pause`` looks like an allowed
    ``cms.services`` facade import. This AST pass recovers the imported name and,
    when it is private (starts with ``_``) and the module belongs to one of our
    layers, reconstructs the effective dotted target (``cms.services._range_pause``).
    Relative imports (``from ._x import y``) and public names are ignored.
    """
    targets: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return targets

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
            continue
        if node.module.split(".")[0] not in LAYERS:
            continue
        targets.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name.startswith("_"))
    return targets


def _is_public_facade_descendant(module: str, facade: str) -> bool:
    """True when ``module`` is a PUBLIC descendant module of ``facade``.

    ``engine.services.runtime`` is a descendant of ``engine.services``. A private
    component anywhere in the remainder (``engine.services._x``) is not, because
    private split-package modules are already rejected by ADR-001-R1; this keeps
    the two rules from double-reporting the same import.
    """
    if not module.startswith(facade + "."):
        return False
    remainder = module[len(facade) + 1 :]
    return not any(part.startswith("_") for part in remainder.split("."))


def iter_facade_symbol_imports(text: str, restricted_facades: set[str]) -> "tuple[dict[str, set[str]], set[str]]":
    """Return (public symbols imported per restricted facade, non-facade bypasses).

    The only sanctioned shape for a symbol-restricted facade (ADR-001-R4) is an
    absolute ``from <facade> import <name>``; its public names feed the allowlist
    check. Every other shape that reaches the facade or one of its public
    descendants is a bypass: a relative ``from ..<facade> import name``, a
    descendant ``from <facade>.sub import name``, a bare ``import <facade>``, or
    ``import <facade>.sub``. Private ``_``-prefixed targets are left to the
    public-facade rule (ADR-001-R1) so the two rules do not double-report.
    """
    from_symbols: dict[str, set[str]] = {}
    module_bypass: set[str] = set()
    if not restricted_facades:
        return from_symbols, module_bypass
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return from_symbols, module_bypass

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module
            if not module:
                continue
            for facade in restricted_facades:
                if node.level == 0 and module == facade:
                    for alias in node.names:
                        if not alias.name.startswith("_"):
                            from_symbols.setdefault(facade, set()).add(alias.name)
                elif module == facade or _is_public_facade_descendant(module, facade):
                    # Relative facade import (level > 0) or a facade descendant.
                    module_bypass.add(module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for facade in restricted_facades:
                    if alias.name == facade or _is_public_facade_descendant(alias.name, facade):
                        module_bypass.add(alias.name)
    return from_symbols, module_bypass


def _symbol_facade_violations(
    rel: str,
    from_layer: str,
    text: str,
    allowed_symbols: dict[str, dict[str, list[str]]],
) -> list[Violation]:
    """Return ADR-001-R4 per-symbol facade-allowlist violations for one file."""
    restrictions = allowed_symbols.get(from_layer, {})
    if not restrictions:
        return []

    violations: list[Violation] = []
    from_symbols, module_bypass = iter_facade_symbol_imports(text, set(restrictions))
    for facade, names in sorted(from_symbols.items()):
        allowed_names = set(restrictions.get(facade, []))
        for name in sorted(names):
            if name not in allowed_names:
                violations.append(
                    Violation(
                        "layer-imports",
                        "ADR-001-R4",
                        rel,
                        f"{from_layer} may import only sanctioned symbols from {facade}; "
                        f"'{name}' is not allowed (front control-plane operations through cms.services)",
                    )
                )
    for module in sorted(module_bypass):
        violations.append(
            Violation(
                "layer-imports",
                "ADR-001-R4",
                rel,
                f"{from_layer} may not reach {module} except via 'from <facade> import <sanctioned symbol>' "
                "(no relative, descendant, or bare-module imports of the restricted facade)",
            )
        )
    return violations


def check_layer_imports(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Check the layer import policy against selected files."""
    violations: list[Violation] = []
    config_path = repo_root / "scripts" / "check_layer_imports" / "layer_imports.yaml"
    allowed = load_allowed_imports(config_path)
    allowed_symbols = load_allowed_symbols(config_path)

    for rel, from_layer in iter_layer_files(repo_root, files):
        text = (repo_root / rel).read_text(encoding="utf-8")
        regex_modules = set(IMPORT_PATTERN.findall(text))
        # AST recovers `from facade import _private`, which the regex sees only
        # as the allowed facade module path.
        private_modules = iter_private_facade_imports(text)
        for module in sorted(regex_modules | private_modules):
            to_layer = module.split(".", 1)[0]
            if to_layer == from_layer:
                continue
            if not is_import_allowed(from_layer, module, allowed):
                violations.append(
                    Violation(
                        "layer-imports",
                        "ADR-001-R1",
                        rel,
                        f"{from_layer} may not import {module}",
                    )
                )
        # ADR-001-R4: symbol-restricted facade seams (e.g. mission_control ->
        # engine.services) permit only the enumerated data-plane symbols.
        violations.extend(_symbol_facade_violations(rel, from_layer, text, allowed_symbols))
        if from_layer != CYBERSCRIPT_ALLOWED_LAYER:
            for module in sorted(set(CYBERSCRIPT_IMPORT_PATTERN.findall(text))):
                violations.append(
                    Violation(
                        "layer-imports",
                        "ADR-001-R1",
                        rel,
                        f"{from_layer} may not import {module}; use shared shims",
                    )
                )

    return violations


def check_cross_layer_model_imports(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Find direct cross-layer model imports in selected runtime files."""
    violations: list[Violation] = []

    for rel, from_layer in iter_layer_files(repo_root, files):
        text = (repo_root / rel).read_text(encoding="utf-8")
        for module in sorted(set(IMPORT_PATTERN.findall(text))):
            parts = module.split(".")
            to_layer = parts[0]
            if to_layer == from_layer:
                continue
            if len(parts) >= 2 and parts[1] == "models":
                violations.append(
                    Violation(
                        "cross-layer-model-imports",
                        "ADR-001-R2",
                        rel,
                        f"{from_layer} imports {module}; prefer a service seam or shared contract",
                    )
                )

    return violations


_PLATFORM_REL = "shifter/shifter_platform"
_SETTINGS_REL = "shifter/shifter_platform/config/settings.py"
_LAYER_POLICY_REL = "scripts/check_layer_imports/layer_imports.yaml"


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


def _parse_installed_apps(settings_text: str) -> tuple[list[str], list[str]]:
    """Return (resolved app strings, unresolved dynamic reprs) from INSTALLED_APPS.

    Parses the ``INSTALLED_APPS = [...]`` literal plus ``INSTALLED_APPS.append(...)``
    calls. Any entry that is not a string constant — a dynamic expression, or an
    ``extend``/``insert`` mutation — is returned as unresolved so the check fails
    closed rather than silently skipping it.
    """
    resolved: list[str] = []
    unresolved: list[str] = []

    def _collect_sequence(value: ast.expr, dynamic_detail: str) -> None:
        """Add string-literal elements of a list/tuple; flag anything else."""
        if isinstance(value, (ast.List, ast.Tuple)):
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    resolved.append(elt.value)
                else:
                    unresolved.append("non-literal INSTALLED_APPS entry")
        else:
            unresolved.append(dynamic_detail)

    tree = ast.parse(settings_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "INSTALLED_APPS":
                    _collect_sequence(node.value, "INSTALLED_APPS not assigned a list/tuple literal")
        elif isinstance(node, ast.AugAssign):
            # INSTALLED_APPS += [...] / += SOME_APPS
            target = node.target
            if isinstance(target, ast.Name) and target.id == "INSTALLED_APPS" and isinstance(node.op, ast.Add):
                _collect_sequence(node.value, "unresolvable INSTALLED_APPS += mutation")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if isinstance(func.value, ast.Name) and func.value.id == "INSTALLED_APPS":
                if func.attr == "append":
                    arg = node.args[0] if node.args else None
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        resolved.append(arg.value)
                    else:
                        unresolved.append("non-literal INSTALLED_APPS.append() argument")
                elif func.attr in {"extend", "insert", "__iadd__", "__add__"}:
                    unresolved.append(f"unresolvable INSTALLED_APPS.{func.attr}() mutation")
    return resolved, unresolved


def check_installed_apps_classified(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Fail closed when a first-party INSTALLED_APPS app is unclassified (#1523).

    Enforces set-equality between the canonical classification
    (layer_imports.yaml), the tracked local AppConfig packages, and the
    first-party apps actually installed. Adding a local app to INSTALLED_APPS
    without classifying it, leaving a stale classification entry, or introducing
    a dynamic INSTALLED_APPS entry the checker cannot resolve, all fail closed.
    """
    del files  # whole-tree invariant; not file-scoped
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


def _is_guardrail_file(path: str) -> bool:
    return path in GUARDRAIL_FILES or any(path.startswith(prefix) for prefix in GUARDRAIL_PREFIXES)


def _is_docs_file(path: str) -> bool:
    return any(path == item or path.startswith(item) for item in DOC_PATHS)


def check_guardrail_docs(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Require documentation updates when guardrails change."""
    if not files:
        return []

    touched_guardrails = [path for path in files if _is_guardrail_file(path)]
    if not touched_guardrails:
        return []

    if any(_is_docs_file(path) for path in files):
        return []

    first_path = touched_guardrails[0]
    return [
        Violation(
            "guardrail-docs",
            "ADR-002-R1",
            first_path,
            "Guardrail changes must update docs/adr or the developer ADR enforcement docs in the same change",
        )
    ]


def check_no_agent_attribution(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Reject AI/agent marketing or co-author attribution in tracked text."""
    from agent_attribution import find_agent_attribution_matches

    candidates = files
    if candidates is None:
        candidates = [
            rel
            for rel in subprocess.check_output(["git", "ls-files"], cwd=repo_root, text=True).splitlines()
            if rel
        ]

    violations: list[Violation] = []
    for rel in candidates:
        if rel in _AGENT_ATTRIBUTION_SCAN_SKIP:
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        matches = find_agent_attribution_matches(text)
        if not matches:
            continue
        first = matches[0]
        violations.append(
            Violation(
                "no-agent-attribution",
                "ADR-002-R2",
                rel,
                f"Prohibited AI/agent attribution ({first.rule}): {first.excerpt}",
            )
        )
    return violations


DOCS_COVERAGE_MANIFEST = "docs/adr/documentation-coverage.yaml"
DOCS_COVERAGE_RULE_ID = "ADR-022-R1"
_AGENT_ATTRIBUTION_SCAN_SKIP = {
    "scripts/adr_guard/agent_attribution.py",
    "scripts/adr_guard/block_agent_attribution_commit_msg.py",
    "scripts/adr_guard/tests/test_agent_attribution.py",
}
_DOCS_EXCLUDED_PART = "_deprecated"
_MARKDOWN_LINK_PATTERN = re.compile(r"\]\(([^)\s]+)")


def _normalize_doc_slug(value: str) -> str:
    """Normalize a posix doc slug, resolving ``.``/``..`` segments."""
    segments: list[str] = []
    for segment in value.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    return "/".join(segments)


def _doc_path_is_excluded(slug: str) -> bool:
    """A doc under a ``_deprecated`` or hidden path part is not serveable."""
    return any(part == _DOCS_EXCLUDED_PART or part.startswith(".") for part in slug.split("/") if part)


def _collect_index_link_slugs(docs_root: Path) -> set[str]:
    """Return the set of docs-root-relative slugs linked from any index.md."""
    linked: set[str] = set()
    if not docs_root.is_dir():
        return linked
    for index_file in docs_root.rglob("index.md"):
        rel_parts = index_file.relative_to(docs_root).parts
        if any(part == _DOCS_EXCLUDED_PART or part.startswith(".") for part in rel_parts):
            continue
        index_dir = "/".join(rel_parts[:-1])
        try:
            text = index_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in _MARKDOWN_LINK_PATTERN.findall(text):
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "/")):
                continue
            if target.endswith(".md"):
                target = target[: -len(".md")]
            linked.add(_normalize_doc_slug(f"{index_dir}/{target}"))
    return linked


def check_documentation_coverage(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Require every major feature to carry user and technical documentation.

    The coverage manifest (``docs/adr/documentation-coverage.yaml``) is the
    source of truth, so the check validates the whole manifest on every run
    regardless of ``files`` (like ``check_adr_registry``). Each feature must
    declare at least one user doc and one technical doc; every referenced doc
    must exist as a serveable file under the in-app docs tree (not under a
    ``_deprecated``/hidden path) and be reachable from an ``index.md``.
    """
    manifest_path = repo_root / DOCS_COVERAGE_MANIFEST
    try:
        manifest = _load_json_yaml(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as err:
        return [Violation("documentation-coverage", DOCS_COVERAGE_RULE_ID, DOCS_COVERAGE_MANIFEST, str(err))]

    if not isinstance(manifest, dict):
        return [
            Violation(
                "documentation-coverage",
                DOCS_COVERAGE_RULE_ID,
                DOCS_COVERAGE_MANIFEST,
                "documentation coverage manifest must be a JSON object",
            )
        ]

    docs_root_rel = manifest.get("docs_root")
    features = manifest.get("features")
    if not isinstance(docs_root_rel, str) or not isinstance(features, list):
        return [
            Violation(
                "documentation-coverage",
                DOCS_COVERAGE_RULE_ID,
                DOCS_COVERAGE_MANIFEST,
                "manifest must define a string 'docs_root' and a list of 'features'",
            )
        ]

    docs_root = repo_root / docs_root_rel
    linked_slugs = _collect_index_link_slugs(docs_root)
    violations: list[Violation] = []

    for feature in features:
        if not isinstance(feature, dict):
            violations.append(
                Violation(
                    "documentation-coverage",
                    DOCS_COVERAGE_RULE_ID,
                    DOCS_COVERAGE_MANIFEST,
                    "each feature entry must be a JSON object",
                )
            )
            continue
        feature_id = feature.get("id") or "<unknown>"
        user_docs = feature.get("user_docs") or []
        technical_docs = feature.get("technical_docs") or []
        if not user_docs:
            violations.append(
                Violation(
                    "documentation-coverage",
                    DOCS_COVERAGE_RULE_ID,
                    DOCS_COVERAGE_MANIFEST,
                    f"feature {feature_id} must declare at least one user doc",
                )
            )
        if not technical_docs:
            violations.append(
                Violation(
                    "documentation-coverage",
                    DOCS_COVERAGE_RULE_ID,
                    DOCS_COVERAGE_MANIFEST,
                    f"feature {feature_id} must declare at least one technical doc",
                )
            )
        for rel in list(user_docs) + list(technical_docs):
            slug = _normalize_doc_slug(rel)
            doc_path = f"{docs_root_rel}/{slug}"
            if _doc_path_is_excluded(slug):
                violations.append(
                    Violation(
                        "documentation-coverage",
                        DOCS_COVERAGE_RULE_ID,
                        doc_path,
                        f"feature {feature_id} references a deprecated or hidden doc that is not served",
                    )
                )
                continue
            if not (docs_root / slug).is_file():
                violations.append(
                    Violation(
                        "documentation-coverage",
                        DOCS_COVERAGE_RULE_ID,
                        doc_path,
                        f"feature {feature_id} references a missing doc",
                    )
                )
                continue
            doc_slug = slug[: -len(".md")] if slug.endswith(".md") else slug
            if doc_slug not in linked_slugs:
                violations.append(
                    Violation(
                        "documentation-coverage",
                        DOCS_COVERAGE_RULE_ID,
                        doc_path,
                        f"feature {feature_id} references an orphaned doc not linked from any index.md",
                    )
                )

    return violations


CLOUD_ROOTS = (
    "shifter/shifter_platform/shared/cloud",
    "shifter/engine/provisioner/cloud",
)
CLOUD_SKIP_FILES = {"__init__.py", "base.py"}


def check_cloud_factory_seam(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Ensure cloud adapter parity between AWS and GCP (ADR-005-R1).

    Every adapter module in cloud/aws/ must have a counterpart in cloud/gcp/
    and vice versa.  Modules named __init__.py and base.py are excluded since
    they serve structural rather than adapter roles.
    """
    if files is not None:
        cloud_touched = any(any(f.startswith(root + "/") for root in CLOUD_ROOTS) for f in files)
        if not cloud_touched:
            return []

    violations: list[Violation] = []
    for root in CLOUD_ROOTS:
        aws_dir = repo_root / root / "aws"
        gcp_dir = repo_root / root / "gcp"
        if not aws_dir.exists() or not gcp_dir.exists():
            continue
        aws_modules = {f.name for f in aws_dir.glob("*.py")} - CLOUD_SKIP_FILES
        gcp_modules = {f.name for f in gcp_dir.glob("*.py")} - CLOUD_SKIP_FILES
        for missing in sorted(aws_modules - gcp_modules):
            violations.append(
                Violation(
                    "cloud-factory-seam",
                    "ADR-005-R1",
                    f"{root}/gcp/{missing}",
                    f"AWS adapter {missing} has no GCP counterpart",
                )
            )
        for missing in sorted(gcp_modules - aws_modules):
            violations.append(
                Violation(
                    "cloud-factory-seam",
                    "ADR-005-R1",
                    f"{root}/aws/{missing}",
                    f"GCP adapter {missing} has no AWS counterpart",
                )
            )
    return violations


# child_process import shapes we care about (any form — named, default,
# namespace, CJS destructure, bare CJS require — with or without the
# `node:` prefix). We require the import as evidence that this file
# really pulls Node's child_process; without it, an `execSync` token
# could be an unrelated function with the same name.
_CHILD_PROCESS_IMPORT = re.compile(
    r"""(?x)
    (
        from\s*["'](?:node:)?child_process["']
    )
    |
    (
        require\s*\(\s*["'](?:node:)?child_process["']\s*\)
    )
    """,
)
# `execSync as <alias>` in an ESM named-import. Captures the alias
# so we can search for `<alias>(` as a call site too.
_EXEC_SYNC_ALIAS = re.compile(r"\bexecSync\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)")


# Tiny per-state helpers for _strip_js_comments_and_strings.
# Splitting the state machine across these helpers keeps per-function
# cognitive complexity low and avoids a single mega-regex whose
# alternation complexity tripped SonarCloud. Each helper consumes one
# or two characters and returns the next loop state.

_BLANK_KEEP_NEWLINES = {"\n": "\n"}


def _blank_for(ch: str) -> str:
    return _BLANK_KEEP_NEWLINES.get(ch, " ")


def _consume_code(text: str, i: int) -> tuple[int, str, str, str]:
    """Code state. Detects start of comment / string / nothing."""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "/" and nxt == "/":
        return i + 2, "  ", "line_comment", ""
    if ch == "/" and nxt == "*":
        return i + 2, "  ", "block_comment", ""
    if ch in ("'", '"', "`"):
        return i + 1, " ", "string", ch
    return i + 1, ch, "code", ""


def _consume_line_comment(text: str, i: int) -> tuple[int, str, str, str]:
    ch = text[i]
    if ch == "\n":
        return i + 1, "\n", "code", ""
    return i + 1, " ", "line_comment", ""


def _consume_block_comment(text: str, i: int) -> tuple[int, str, str, str]:
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "*" and nxt == "/":
        return i + 2, "  ", "code", ""
    return i + 1, _blank_for(ch), "block_comment", ""


def _consume_string(text: str, i: int, quote: str) -> tuple[int, str, str, str]:
    nxt = text[i + 1] if i + 1 < len(text) else ""
    ch = text[i]
    if ch == "\\" and nxt:
        # Two-char escape consumed as whitespace; backslash never
        # closes the string prematurely.
        return i + 2, "  ", "string", quote
    if ch == quote:
        return i + 1, " ", "code", ""
    return i + 1, _blank_for(ch), "string", quote


def _strip_line_comment(text: str, i: int, n: int) -> tuple[str, int]:
    """Consume a `//` line comment starting at `i` and return
    `(spaces, new_index)`. Newlines are preserved so line numbers
    stay correct."""
    end = text.find("\n", i + 2)
    if end == -1:
        return " " * (n - i), n
    return " " * (end - i), end


def _strip_block_comment(text: str, i: int, n: int) -> tuple[str, int]:
    """Consume a `/* */` block comment starting at `i`. Replace its
    body with whitespace; preserve newlines."""
    end = text.find("*/", i + 2)
    if end == -1:
        return " " * (n - i), n
    segment = text[i : end + 2]
    return "".join(c if c == "\n" else " " for c in segment), end + 2


def _scan_to_closing_quote(text: str, start: int, n: int, quote: str) -> int:
    """Return the index just past the matching closing quote starting
    at `start`. Handles backslash escapes."""
    j = start
    while j < n:
        if text[j] == "\\" and j + 1 < n:
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return j


def _strip_js_comments_only(text: str) -> str:
    """Replace JS `//` and `/* */` comment contents with whitespace,
    preserve string-literal contents verbatim.

    Used by `mcp-ops-tls-strict` (#1190 / codex review #1180 cycle 1
    finding 7): the previous full strip erased quoted property keys
    like `{ "rejectUnauthorized": false }` along with the legitimate
    string-literal documentation neighbours. Stripping only comments
    keeps the quoted-key form visible to the regex while still
    suppressing false-positives from explanatory `//` comments.
    """
    out: list[str] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            emit, i = _strip_line_comment(text, i, n)
            out.append(emit)
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            emit, i = _strip_block_comment(text, i, n)
            out.append(emit)
            continue
        if ch in ('"', "'"):
            end = _scan_to_closing_quote(text, i + 1, n, ch)
            out.append(text[i:end])
            i = end
            continue
        if ch == "`":
            end = _scan_to_closing_quote(text, i + 1, n, "`")
            out.append(text[i:end])
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_js_comments_and_strings(text: str) -> str:
    """Flatten JS string-literal and comment contents to whitespace.

    Newlines are preserved so error positions stay sane and so `^` /
    line-mode regexes still work. Template-literal substitutions
    (`${...}`) are intentionally not parsed; an `execSync(` inside a
    `` `${...}` `` substitution is a vanishingly rare bypass and falls
    under code-review, not regex.
    """
    out: list[str] = []
    n = len(text)
    i = 0
    state = "code"
    quote = ""
    while i < n:
        if state == "code":
            i, emit, state, quote = _consume_code(text, i)
        elif state == "line_comment":
            i, emit, state, quote = _consume_line_comment(text, i)
        elif state == "block_comment":
            i, emit, state, quote = _consume_block_comment(text, i)
        else:  # state == "string"
            i, emit, state, quote = _consume_string(text, i, quote)
        out.append(emit)
    return "".join(out)


def _build_call_site_pattern(aliases: list[str]) -> re.Pattern[str]:
    """Pattern matching `execSync(` / `exec(` and any captured alias `(`.

    `exec` and `execSync` are the two child_process call shapes that
    take a shell command string. `spawnSync(... { shell: true })` is
    handled by a separate matcher because it requires looking at the
    options object as well as the function name.

    Using `(?<![A-Za-z0-9_$])` rejects unrelated identifiers that
    happen to end in `exec` or `execSync` (e.g. `myExecSync`,
    `regexExec`).
    """
    names = ["execSync", "exec", *aliases]
    alt = "|".join(re.escape(name) for name in names)
    return re.compile(rf"(?<![A-Za-z0-9_$])(?:{alt})\s*\(")


# `spawn` / `spawnSync` / `execFile` / `execFileSync` with
# `{ shell: true }` is just as bad as `exec` from a shell-string
# point of view; the option re-routes the call through `/bin/sh -c`.
# We match the function name immediately followed (eventually) by an
# options object that contains `shell: true`. Because we cannot parse
# JS in a regex, the matcher is intentionally generous: any `shell:
# true` within ~400 characters of a `spawn`/`execFile` call counts.
_SHELL_TRUE_SPAWN = re.compile(
    r"""(?xs)
    (?<![A-Za-z0-9_$])
    (?:spawnSync|spawn|execFileSync|execFile)
    \s*\([^)]{0,400}?
    \bshell\s*:\s*true\b
    """,
)


def check_mcp_no_shell_exec(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid execSync call sites in mcp/ servers (ADR-010-R1).

    Static lower bound for catching shell-string aws-cli invocations:
    if a file under mcp/ both imports `child_process` (in any form —
    named ESM, default ESM, namespace ESM, named CJS, or whole-module
    CJS — including the `node:` prefix) AND contains an `execSync(`
    or aliased call site (`import { execSync as run } ... run(...)`),
    flag it. String literals and comments are flattened to whitespace
    first so they cannot false-positive trip the check or hide a
    real call site. Exceptions (e.g. mcp/ngfw) are filtered through
    docs/adr/exceptions.yaml.

    Static analysis cannot catch every motivated bypass (e.g.
    `const run = cp.execSync; run(...)`); ADR-010 is enforced at
    multiple layers and the static check is the cheap pre-commit
    backstop, not the only line of defence.
    """
    mcp_root = repo_root / "mcp"
    if not mcp_root.exists():
        return []

    if files is not None:
        candidate_paths = [
            repo_root / path for path in files if path.startswith("mcp/") and path.endswith((".js", ".mjs", ".cjs"))
        ]
    else:
        candidate_paths = [
            p
            for p in mcp_root.rglob("*")
            if p.is_file() and p.suffix in (".js", ".mjs", ".cjs") and "node_modules" not in p.parts
        ]

    violations: list[Violation] = []
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Import detection runs on raw text so the matched
        # `"child_process"` string literal is preserved.
        if not _CHILD_PROCESS_IMPORT.search(text):
            continue
        # Alias and call-site detection run on the comment-and-string
        # flattened form so that an `execSync(` token inside a comment
        # or string cannot trigger the check, a real `execSync(` call
        # on a line containing a URL like `"https://..."` is not
        # erased, and a comment like `// execSync as run` cannot
        # synthesise a fake alias that turns innocent `run(` calls
        # into false positives.
        stripped = _strip_js_comments_and_strings(text)
        aliases = _EXEC_SYNC_ALIAS.findall(stripped)
        call_pattern = _build_call_site_pattern(aliases)
        rel = _repo_relative(path, repo_root)
        if call_pattern.search(stripped):
            violations.append(
                Violation(
                    "mcp-no-shell-exec",
                    "ADR-010-R1",
                    rel,
                    "Calls exec/execSync from child_process; MCP servers must invoke external CLIs via argv arrays (spawn/spawnSync/execFile)",
                )
            )
        elif _SHELL_TRUE_SPAWN.search(stripped):
            violations.append(
                Violation(
                    "mcp-no-shell-exec",
                    "ADR-010-R1",
                    rel,
                    "Uses spawn/spawnSync/execFile/execFileSync with { shell: true }; MCP servers must invoke external CLIs via argv arrays without a shell",
                )
            )
    return violations


# Issue #1190 — mcp/ops Postgres TLS verification must stay on. This
# is a defense-in-depth backstop for `mcp/ops/lib.js::buildPoolConfig`,
# which is the single place that builds the pg.Pool TLS config. The
# guardrail flags any other file under `mcp/ops/` that introduces
# `rejectUnauthorized: false` (or `0`/`null`), even in a different
# call site, before code review notices.
#
# The regex matches BOTH the unquoted `rejectUnauthorized: false`
# property form AND the quoted property-name forms
# `"rejectUnauthorized": false` / `'rejectUnauthorized': false`.
# Stripping JS strings before matching would erase the quoted-key
# form (codex #1180 cycle 1 finding 7) so we match against raw text.
# A comment line literally containing this token is rare enough that
# the false-positive risk is bounded; in that case the reviewer
# rewrites the comment, which is the right outcome anyway.
_REJECT_UNAUTH_FALSE = re.compile(
    r"""["']?rejectUnauthorized["']?\s*:\s*(?:false|0|null)\b""",
    re.IGNORECASE,
)


def check_mcp_ops_tls_strict(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid `rejectUnauthorized: false` under mcp/ops (ADR-014-R7).

    The `mcp/ops` MCP server connects to RDS Postgres via an SSM port
    forward. Issue #1190 — the previous implementation disabled TLS
    verification to work around the cert/host mismatch caused by the
    tunnel. `buildPoolConfig` (in `mcp/ops/lib.js`) now sets
    `ssl.servername` to the captured RDS endpoint so verification fires
    against the real RDS cert; the `rejectUnauthorized: false` escape
    hatch is removed.

    This check scans the JS/MJS/CJS files under `mcp/ops/` (excluding
    `node_modules/`) for any reintroduction of
    `rejectUnauthorized: false` (or `0`/`null`). Matches both
    unquoted property keys (`rejectUnauthorized: false`) and quoted
    property keys (`"rejectUnauthorized": false`,
    `'rejectUnauthorized': false`) so JSON-shaped config cannot
    re-introduce the setting under the guard's nose.
    """
    ops_root = repo_root / "mcp" / "ops"
    if not ops_root.exists():
        return []

    if files is not None:
        candidate_paths = [
            repo_root / path
            for path in files
            if path.startswith("mcp/ops/") and path.endswith((".js", ".mjs", ".cjs"))
        ]
    else:
        candidate_paths = [
            p
            for p in ops_root.rglob("*")
            if p.is_file()
            and p.suffix in (".js", ".mjs", ".cjs")
            and "node_modules" not in p.parts
        ]

    violations: list[Violation] = []
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Strip comments only (not strings) so:
        #   - `// rejectUnauthorized: false` doc comments do not trip.
        #   - quoted-key forms `{ "rejectUnauthorized": false }` still
        #     match the regex (codex review #1180 cycle 1 finding 7).
        comment_stripped = _strip_js_comments_only(text)
        if _REJECT_UNAUTH_FALSE.search(comment_stripped):
            rel = _repo_relative(path, repo_root)
            violations.append(
                Violation(
                    check="mcp-ops-tls-strict",
                    rule_id="ADR-014-R7",
                    path=rel,
                    message=(
                        "Postgres TLS verification must stay enabled. "
                        "Use buildPoolConfig() in mcp/ops/lib.js, which sets "
                        "ssl.servername to the captured RDS endpoint so cert "
                        "verification fires against RDS, not localhost."
                    ),
                )
            )
    return violations


K8S_BASE_DEPLOYMENT_DIR = "platform/k8s/gcp/base"
HELM_CHART_DIR = "platform/charts/shifter"
# Values files to render for ADR-006-R2 validation. Mirrors the helm-lint
# pre-commit hook's input set so the guard validates the same chart-rendered
# output devs already lint locally.
HELM_VALUES_FILES = (
    "platform/charts/shifter/values-gcp-dev.yaml",
    "platform/charts/shifter/values-gcp-prod.yaml",
)


def _is_real_int(value: object) -> bool:
    """True when value is an int but not a bool (bool subclasses int in Python)."""
    return type(value) is int  # noqa: E721 - intentional exact type check


def _check_k8s_pod_security(pod_sc: dict, rel: str) -> list[Violation]:
    seccomp = pod_sc.get("seccompProfile") or {}
    if not isinstance(seccomp, dict):
        seccomp = {}
    seccomp_type = seccomp.get("type")
    if seccomp_type != "RuntimeDefault":
        return [
            Violation(
                "k8s-deployment-security-context",
                "ADR-006-R2",
                rel,
                f"pod-level securityContext.seccompProfile.type must be 'RuntimeDefault' (got {seccomp_type!r})",
            )
        ]
    return []


def _effective_field(container_sc: dict, pod_sc: dict, key: str) -> object:
    """Resolve a securityContext field that K8s lets the pod default cover.

    Per the Pod spec, container-level overrides take precedence; if the
    container does not set the field, the pod-level value applies. Used
    for runAsNonRoot, runAsUser, runAsGroup.
    """
    if key in container_sc:
        return container_sc.get(key)
    return pod_sc.get(key)


def _coerce_container_sc(raw_sc: object, label: str) -> tuple[dict, list[Violation]]:
    """Coerce a container's `securityContext` into a dict, surfacing structural problems.

    Non-mapping values (YAML aliases resolved to scalars, malformed shapes)
    produce a violation and the caller continues against an empty dict so
    individual field checks don't AttributeError.
    """
    if raw_sc is not None and not isinstance(raw_sc, dict):
        return (
            {},
            [
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    "",  # rel filled in by caller
                    f"{label} securityContext must be a mapping "
                    "(YAML aliases or non-mapping values are not supported by this guard)",
                )
            ],
        )
    return (raw_sc or {}, [])


def _check_container_basic_fields(sc: dict, label: str) -> list[str]:
    """Per-container fields that don't inherit from the pod (ADR-006-R2)."""
    msgs: list[str] = []
    if sc.get("privileged") is True:
        msgs.append(f"{label} must not set securityContext.privileged: true")
    if sc.get("allowPrivilegeEscalation") is not False:
        msgs.append(f"{label} must set allowPrivilegeEscalation: false")
    if sc.get("readOnlyRootFilesystem") is not True:
        msgs.append(f"{label} must set readOnlyRootFilesystem: true")
    return msgs


def _check_container_capabilities(sc: dict, label: str) -> list[str]:
    """capabilities.drop == [ALL] and no capabilities.add key (ADR-006-R2)."""
    msgs: list[str] = []
    capabilities = sc.get("capabilities")
    if capabilities is not None and not isinstance(capabilities, dict):
        msgs.append(f"{label} securityContext.capabilities must be a mapping if set")
        capabilities = {}
    if capabilities is None:
        capabilities = {}
    drop = capabilities.get("drop")
    if drop != ["ALL"]:
        msgs.append(f"{label} must drop ALL capabilities (got {drop!r})")
    if "add" in capabilities:
        msgs.append(
            f"{label} must not set capabilities.add (would re-grant after drop ALL); got {capabilities['add']!r}"
        )
    return msgs


def _check_container_seccomp(sc: dict, label: str) -> list[str]:
    """Container-level seccompProfile.type must be RuntimeDefault when set."""
    block = sc.get("seccompProfile")
    if block is not None and not isinstance(block, dict):
        return [f"{label} securityContext.seccompProfile must be a mapping if set"]
    seccomp_type = (block or {}).get("type")
    if seccomp_type is not None and seccomp_type != "RuntimeDefault":
        return [f"{label} container-level seccompProfile.type must be 'RuntimeDefault' if set (got {seccomp_type!r})"]
    return []


def _check_container_identity(sc: dict, pod_sc: dict, label: str) -> list[str]:
    """runAsNonRoot, runAsUser, runAsGroup with pod-level inheritance."""
    msgs: list[str] = []
    if _effective_field(sc, pod_sc, "runAsNonRoot") is not True:
        msgs.append(f"{label} must set runAsNonRoot: true (directly or via pod-level securityContext)")
    run_as_user = _effective_field(sc, pod_sc, "runAsUser")
    if not _is_real_int(run_as_user) or run_as_user <= 0:
        msgs.append(
            f"{label} runAsUser must be a positive integer "
            f"(directly or via pod-level securityContext); got {run_as_user!r}"
        )
    run_as_group = _effective_field(sc, pod_sc, "runAsGroup")
    if not _is_real_int(run_as_group) or run_as_group <= 0:
        msgs.append(
            f"{label} runAsGroup must be a positive integer "
            f"(directly or via pod-level securityContext); got {run_as_group!r}"
        )
    return msgs


def _check_k8s_container_security(container: dict, pod_sc: dict, rel: str, role: str) -> list[Violation]:
    """Validate a single container or init container's securityContext.

    Honors pod-level inheritance for runAsNonRoot/runAsUser/runAsGroup
    (Kubernetes lets these be set on the pod and inherited by containers
    unless overridden). Container-only fields (allowPrivilegeEscalation,
    capabilities, readOnlyRootFilesystem, privileged) must be set on the
    container itself.
    """
    name = container.get("name", "<unnamed>")
    label = f"{role} {name!r}"
    sc, structural_violations = _coerce_container_sc(container.get("securityContext"), label)

    field_msgs: list[str] = []
    field_msgs += _check_container_basic_fields(sc, label)
    field_msgs += _check_container_capabilities(sc, label)
    field_msgs += _check_container_seccomp(sc, label)
    field_msgs += _check_container_identity(sc, pod_sc, label)

    violations = [Violation("k8s-deployment-security-context", "ADR-006-R2", rel, msg) for msg in field_msgs]
    # Re-stamp rel onto any structural violations from the coercion step.
    for v in structural_violations:
        violations.append(Violation(v.check, v.rule_id, rel, v.message))
    return violations


def _iter_yaml_documents(text: str, rel: str) -> tuple[list[object], list[Violation]]:
    """Parse a (possibly multi-document) YAML file and return docs + parse violations."""
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return (
            [],
            [
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    _ADR_GUARD_PATH,
                    "PyYAML is required to validate K8s deployment security contexts; "
                    "install pyyaml in the runtime environment",
                )
            ],
        )

    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        return (
            [],
            [
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    rel,
                    f"YAML parse error: {exc}",
                )
            ],
        )
    return ([d for d in docs if d is not None], [])


def _v(rel: str, msg: str) -> Violation:
    """Shorthand: ADR-006-R2 violation builder for the K8s deployment check."""
    return Violation("k8s-deployment-security-context", "ADR-006-R2", rel, msg)


def _resolve_pod_spec(doc: dict, rel: str) -> tuple[dict | None, list[Violation]]:
    """Walk doc.spec.template.spec, validating each level is a mapping.

    Returns (pod_spec_or_None, violations). When any level is non-mapping,
    pod_spec is None and the caller skips the per-document checks.
    """
    spec = doc.get("spec")
    if spec is not None and not isinstance(spec, dict):
        return None, [_v(rel, f"spec must be a mapping (got {type(spec).__name__})")]
    spec = spec or {}

    template = spec.get("template")
    if template is not None and not isinstance(template, dict):
        return None, [_v(rel, f"spec.template must be a mapping (got {type(template).__name__})")]
    template = template or {}

    pod_spec = template.get("spec")
    if pod_spec is not None and not isinstance(pod_spec, dict):
        return None, [
            _v(
                rel,
                f"spec.template.spec must be a mapping (got {type(pod_spec).__name__})",
            )
        ]
    return pod_spec or {}, []


def _resolve_pod_sc(pod_spec: dict, rel: str) -> tuple[dict, list[Violation]]:
    """Coerce pod_spec.securityContext to a dict, surfacing structural problems."""
    pod_sc = pod_spec.get("securityContext") or {}
    if not isinstance(pod_sc, dict):
        return {}, [
            _v(
                rel,
                "spec.template.spec.securityContext must be a mapping "
                "(YAML aliases or non-mapping values are not supported by this guard)",
            )
        ]
    return pod_sc, []


def _validate_containers_list(
    pod_spec: dict, pod_sc: dict, rel: str, key: str, role: str, *, required: bool
) -> list[Violation]:
    """Validate every container entry in pod_spec[key]. `required=True` rejects empty/missing."""
    raw = pod_spec.get(key)
    if raw is None and not required:
        return []
    if not isinstance(raw, list) or (required and len(raw) == 0):
        if required:
            return [
                _v(
                    rel,
                    f"spec.template.spec.{key} must be a non-empty list (got {type(raw).__name__})",
                )
            ]
        return []

    violations: list[Violation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            violations.append(_v(rel, f"{role} entry must be a mapping (got {type(entry).__name__})"))
            continue
        violations.extend(_check_k8s_container_security(entry, pod_sc, rel, role))
    return violations


def _validate_deployment_documents(docs: list[object], rel: str) -> list[Violation]:
    """Apply the ADR-006-R2 security-context rule to every Deployment in a parsed document set.

    rel is the file-or-source label included in any Violation produced.
    """
    violations: list[Violation] = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "Deployment":
            continue

        pod_spec, structural = _resolve_pod_spec(doc, rel)
        violations.extend(structural)
        if pod_spec is None:
            continue

        pod_sc, sc_violations = _resolve_pod_sc(pod_spec, rel)
        violations.extend(sc_violations)
        violations.extend(_check_k8s_pod_security(pod_sc, rel))
        violations.extend(_validate_containers_list(pod_spec, pod_sc, rel, "containers", "container", required=True))
        violations.extend(
            _validate_containers_list(pod_spec, pod_sc, rel, "initContainers", "initContainer", required=False)
        )
    return violations


def _render_chart_for_validation(
    repo_root: Path, values_files: tuple[str, ...]
) -> tuple[list[tuple[list[object], str]], list[Violation]]:
    """Run `helm template` for each values file and return (parsed docs, label) pairs.

    Returns (rendered_docs_per_values_file, violations). When helm is not
    available the call returns a single Violation pointing at adr_guard.py
    so CI surfaces the missing prerequisite rather than passing silently.
    """
    chart_dir = repo_root / HELM_CHART_DIR
    if not chart_dir.exists():
        return [], [
            Violation(
                "k8s-deployment-security-context",
                "ADR-006-R2",
                HELM_CHART_DIR,
                "configured Helm chart directory is missing; cannot validate "
                "the authoritative deployment contract per ADR-007",
            )
        ]

    import shutil

    helm = shutil.which("helm")
    if helm is None:
        return [], [
            Violation(
                "k8s-deployment-security-context",
                "ADR-006-R2",
                _ADR_GUARD_PATH,
                "helm CLI is required to render the chart for ADR-006-R2 validation; "
                "install helm in the runtime environment "
                "(CI installs it in the adr-conformance and adr-guard-tests jobs)",
            )
        ]

    rendered: list[tuple[list[object], str]] = []
    violations: list[Violation] = []
    for vf in values_files:
        values_path = repo_root / vf
        if not values_path.exists():
            violations.append(
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    vf,
                    "configured Helm values file is missing; cannot validate this environment's chart-rendered output",
                )
            )
            continue
        result = subprocess.run(
            [helm, "template", str(chart_dir), "-f", str(values_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            violations.append(
                Violation(
                    "k8s-deployment-security-context",
                    "ADR-006-R2",
                    vf,
                    f"helm template failed: {result.stderr.strip() or result.stdout.strip()}",
                )
            )
            continue
        # Violation.path stays repo-relative (the values file) so existing
        # exception globs in docs/adr/exceptions.yaml can match. The render
        # context goes in messages via _validate_deployment_documents, which
        # callers extend with their own context if needed.
        docs, parse_violations = _iter_yaml_documents(result.stdout, vf)
        violations.extend(parse_violations)
        rendered.append((docs, vf))
    return rendered, violations


def _scan_targets(repo_root: Path, files: list[str] | None) -> tuple[bool, bool, list[Path]]:
    """Decide whether to scan base manifests, chart, and which base files to read.

    --all/CI mode (`files is None`) always exercises the chart branch so a
    missing chart directory surfaces as a violation. files-mode (pre-commit)
    triggers each branch only when the changed file set actually overlaps.
    """
    base_dir = repo_root / K8S_BASE_DEPLOYMENT_DIR
    if files is None:
        scan_base = base_dir.exists()
        base_files = sorted(list(base_dir.rglob("*.yaml")) + list(base_dir.rglob("*.yml"))) if scan_base else []
        return scan_base, True, base_files

    scan_base = False
    scan_chart = False
    base_files: list[Path] = []
    for f in files:
        if f.startswith(K8S_BASE_DEPLOYMENT_DIR + "/") and f.endswith((".yaml", ".yml")):
            scan_base = True
            full = repo_root / f
            if full.exists():
                base_files.append(full)
        if f.startswith(HELM_CHART_DIR + "/"):
            scan_chart = True
    return scan_base, scan_chart, base_files


def _validate_base_files(repo_root: Path, base_files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in base_files:
        rel = _repo_relative(path, repo_root)
        docs, parse_violations = _iter_yaml_documents(path.read_text(encoding="utf-8"), rel)
        violations.extend(parse_violations)
        violations.extend(_validate_deployment_documents(docs, rel))
    return violations


def _validate_chart_renders(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    rendered, render_violations = _render_chart_for_validation(repo_root, HELM_VALUES_FILES)
    violations.extend(render_violations)
    for docs, label in rendered:
        violations.extend(_validate_deployment_documents(docs, label))
    return violations


def _network_policy_violation(path: str, message: str) -> Violation:
    return Violation(
        "k8s-network-policy-coverage",
        "ADR-006-R3",
        path,
        message,
    )


def _as_network_policy_violations(violations: list[Violation]) -> list[Violation]:
    return [_network_policy_violation(violation.path, violation.message) for violation in violations]


def _is_shifter_namespace(name: object) -> bool:
    return isinstance(name, str) and name.startswith("shifter-")


def _document_namespace(doc: object) -> str | None:
    if not isinstance(doc, dict):
        return None
    metadata = doc.get("metadata")
    if not isinstance(metadata, dict):
        return None
    namespace = metadata.get("namespace")
    if isinstance(namespace, str):
        return namespace
    return None


def _collect_shifter_namespaces(docs: list[object]) -> set[str]:
    namespaces: set[str] = set()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        metadata = doc.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if doc.get("kind") == "Namespace":
            name = metadata.get("name")
            if _is_shifter_namespace(name):
                namespaces.add(name)
        namespace = metadata.get("namespace")
        if _is_shifter_namespace(namespace):
            namespaces.add(namespace)
    return namespaces


def _is_default_deny_network_policy(doc: dict) -> bool:
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        return False
    policy_types = spec.get("policyTypes")
    if not isinstance(policy_types, list):
        return False
    if not {"Ingress", "Egress"}.issubset(set(policy_types)):
        return False
    if spec.get("podSelector") != {}:
        return False
    ingress = spec.get("ingress", [])
    egress = spec.get("egress", [])
    return ingress == [] and egress == []


def _network_policy_name(doc: dict) -> str:
    metadata = doc.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
        return metadata["name"]
    return "<unnamed>"


def _shifter_network_policy_docs(docs: list[object]) -> list[tuple[dict, str]]:
    policies: list[tuple[dict, str]] = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "NetworkPolicy":
            continue
        namespace = _document_namespace(doc)
        if not _is_shifter_namespace(namespace):
            continue
        policies.append((doc, namespace))
    return policies


def _default_deny_network_policy_namespaces(
    policies: list[tuple[dict, str]],
) -> set[str]:
    return {namespace for doc, namespace in policies if _is_default_deny_network_policy(doc)}


def _iter_egress_destinations(doc: dict) -> list[tuple[int, object]]:
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        return []
    egress_rules = spec.get("egress", [])
    if not isinstance(egress_rules, list):
        return []

    destinations: list[tuple[int, object]] = []
    for rule_index, rule in enumerate(egress_rules):
        if not isinstance(rule, dict) or not isinstance(rule.get("to"), list):
            continue
        destinations.extend((rule_index, destination) for destination in rule["to"])
    return destinations


def _destination_ip_block_cidr(destination: object) -> object:
    if not isinstance(destination, dict):
        return None
    ip_block = destination.get("ipBlock")
    if not isinstance(ip_block, dict):
        return None
    return ip_block.get("cidr")


def _broad_egress_network_policy_violations(policies: list[tuple[dict, str]], rel: str) -> list[Violation]:
    violations: list[Violation] = []
    broad_cidrs = {"0.0.0.0/0", "::/0"}
    for doc, namespace in policies:
        for rule_index, destination in _iter_egress_destinations(doc):
            cidr = _destination_ip_block_cidr(destination)
            if cidr not in broad_cidrs:
                continue
            violations.append(
                _network_policy_violation(
                    rel,
                    f"NetworkPolicy {namespace}/{_network_policy_name(doc)} "
                    f"egress rule {rule_index} allows broad CIDR {cidr}; "
                    "ADR-006-R3 requires explicit service ranges",
                )
            )
    return violations


def _missing_default_deny_network_policy_violations(
    namespaces: set[str], default_deny_namespaces: set[str], rel: str
) -> list[Violation]:
    return [
        _network_policy_violation(
            rel,
            f"namespace {namespace} lacks a default-deny NetworkPolicy covering both ingress and egress",
        )
        for namespace in sorted(namespaces - default_deny_namespaces)
    ]


def _validate_network_policy_documents(docs: list[object], rel: str) -> list[Violation]:
    namespaces = _collect_shifter_namespaces(docs)
    policies = _shifter_network_policy_docs(docs)
    default_deny_namespaces = _default_deny_network_policy_namespaces(policies)
    return [
        *_broad_egress_network_policy_violations(policies, rel),
        *_missing_default_deny_network_policy_violations(namespaces, default_deny_namespaces, rel),
    ]


def _validate_network_policy_base_files(repo_root: Path, base_files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    docs: list[object] = []
    for path in base_files:
        rel = _repo_relative(path, repo_root)
        parsed, parse_violations = _iter_yaml_documents(path.read_text(encoding="utf-8"), rel)
        docs.extend(parsed)
        violations.extend(_as_network_policy_violations(parse_violations))
    if base_files:
        violations.extend(_validate_network_policy_documents(docs, K8S_BASE_DEPLOYMENT_DIR))
    return violations


def _validate_network_policy_chart_renders(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    rendered, render_violations = _render_chart_for_validation(repo_root, HELM_VALUES_FILES)
    violations.extend(_as_network_policy_violations(render_violations))
    for docs, label in rendered:
        violations.extend(_validate_network_policy_documents(docs, label))
    return violations


def check_k8s_deployment_security_context(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Verify pod, container, and init-container securityContext on Deployments (ADR-006-R2).

    Two enforcement sources are scanned per ADR-006-R2 and ADR-007:

    1. **Base manifest snapshots** under `platform/k8s/gcp/base/` (recursive):
       every YAML document with `kind: Deployment` is validated regardless of
       filename or extension.
    2. **Helm chart rendered output**: the chart at
       `platform/charts/shifter` is rendered via `helm template` for each
       supported values file in `HELM_VALUES_FILES`, and every Deployment
       document in the rendered output is validated. Per ADR-007 the chart is
       the authoritative deployment contract; this catches regressions where
       a chart template or values file removes a required securityContext
       field even if the base snapshots remain compliant.

    Honors pod-level securityContext inheritance for runAsNonRoot, runAsUser,
    and runAsGroup (Kubernetes lets these be set on the pod and inherited by
    containers unless overridden).

    Per Deployment:
    - pod-level seccompProfile.type == 'RuntimeDefault'
    - every container AND initContainer (effective context after pod-level
      inheritance):
      - allowPrivilegeEscalation: false (container-only)
      - capabilities.drop: ['ALL'] AND no capabilities.add (container-only)
      - readOnlyRootFilesystem: true (container-only)
      - privileged: not true (container-only)
      - container-level seccompProfile.type, when set, equals 'RuntimeDefault'
      - runAsNonRoot: true (effective)
      - runAsUser, runAsGroup are positive integers (effective; booleans rejected)
    """
    scan_base, scan_chart, base_files = _scan_targets(repo_root, files)
    if not (scan_base or scan_chart):
        return []

    violations: list[Violation] = []
    if scan_base:
        violations.extend(_validate_base_files(repo_root, base_files))
    if scan_chart:
        violations.extend(_validate_chart_renders(repo_root))
    return violations


def check_k8s_network_policy_coverage(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Verify Shifter namespaces are isolated by default-deny NetworkPolicies."""
    scan_base, scan_chart, base_files = _scan_targets(repo_root, files)
    if not (scan_base or scan_chart):
        return []

    violations: list[Violation] = []
    if scan_base:
        violations.extend(_validate_network_policy_base_files(repo_root, base_files))
    if scan_chart:
        violations.extend(_validate_network_policy_chart_renders(repo_root))
    return violations


_TFVARS_SCOPE = (
    "platform/terraform/environments",
    "platform/terraform/global",
)
_SECRET_NAME_GROUP = (
    r"((?:[A-Za-z_][A-Za-z0-9_]*"
    r"(?:_passwords?|_secrets?|_tokens?|_keys?|_credentials?|_authcodes?|_pin_values?))"
    r"|(?:authcodes?|pin_values?))"
)
_SECRET_VAR_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r'\s*=\s*"[^"]+"',
)
# HCL also supports heredoc string literals (`name = <<EOF` /
# `name = <<-EOF`), which would otherwise bypass the line regex above.
_SECRET_HEREDOC_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*<<-?[A-Za-z_][A-Za-z0-9_]*\s*$",
)
# Object / array assignments to secret-bearing variables. These are
# walked forward to the matching brace/bracket and flagged when any
# string literal appears inside.
_SECRET_BLOCK_OPEN_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*([\{\[])",
)
# Generic single-line assignment to a secret-bearing variable. Used to
# catch function-wrapped string literals like
# `db_password = trimspace("...")` or `api_token = sensitive("...")`
# that the bare-string and block-open patterns above don't cover. The
# RHS is whatever follows `=` on the same line; the violation walker
# then scans for a string literal in that RHS (after stripping trailing
# # / // comments) and flags when present.
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*" + _SECRET_NAME_GROUP + r"\s*=\s*(.+)$",
)
_STRING_LITERAL_PATTERN = re.compile(r'"[^"]+"')
_BLOCK_COMMENT_PATTERN = re.compile(r"/\*.*?\*/", re.DOTALL)
# Variable-name suffixes that mark share-only material (SSH/JWT public
# keys, authorized_keys files, public certificates) so the suffix-based
# regex doesn't over-flag them. Matched against `var_name.endswith(...)`
# so a variable like `public_key_password` is NOT exempted (the secret
# suffix `_password` still wins, even though `public_key` appears in
# the name).
_NON_SECRET_NAME_SUFFIXES = (
    "_public_key",
    "_public_keys",
    "_public_cert",
    "_public_certs",
    "_pub_key",
    "_pub_keys",
    "_pubkey",
    "_pubkeys",
    "_authorized_keys",
    "public_key",
    "public_keys",
    "public_cert",
    "public_certs",
    "pub_key",
    "pub_keys",
    "pubkey",
    "pubkeys",
    "authorized_keys",
)


def _strip_hcl_comments(text: str) -> str:
    """Replace HCL block comments with whitespace (preserving newlines).

    Line comments (`#`, `//`) are handled per-line by the caller so it can
    keep line numbers aligned for violation reporting. Block comments are
    stripped here because they can span lines; we replace each character
    with whitespace except newlines so subsequent regexes still see the
    same line numbers.
    """

    def _blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return _BLOCK_COMMENT_PATTERN.sub(_blank, text)


def _is_line_commented(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("#", "//"))


def _strip_trailing_line_comment(line: str) -> str:
    """Drop trailing `#` or `//` line-comment tail from an HCL line.

    Walks the line keeping track of whether we're inside a `"..."`
    string so a `#` or `//` inside a string is preserved.
    """
    in_string = False
    escape = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "#":
                return line[:i]
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                return line[:i]
        i += 1
    return line


def _balance_scan(chars: str, depth: int) -> tuple[int, bool, bool]:
    """Scan ``chars`` updating the ``()``/``[]``/``{}`` ``depth``.

    Returns ``(new_depth, saw_delimiter, closed_to_zero)``. ``closed_to_zero``
    is ``True`` the moment depth drops to ``<= 0`` — the expression closed
    within ``chars``.
    """
    saw = False
    for ch in chars:
        if ch in "([{":
            depth += 1
            saw = True
        elif ch in ")]}":
            depth -= 1
            saw = True
            if depth <= 0:
                return depth, saw, True
    return depth, saw, False


def _block_depth_scan(chars: str, depth: int, opener: str, closer: str) -> tuple[int, bool]:
    """Scan ``chars`` updating the ``opener``/``closer`` ``depth``.

    Returns ``(new_depth, closed_to_zero)``; ``closed_to_zero`` is ``True``
    the moment depth returns to ``0``.
    """
    for ch in chars:
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return depth, True
    return depth, False


def _scrub_line(line: str) -> str:
    """Blank out ``"..."`` string contents and drop the trailing ``#``/``//``
    line comment so brace/paren counting ignores both.
    """
    return _strip_trailing_line_comment(_STRING_LITERAL_PATTERN.sub('""', line))


def _find_balanced_close_index(lines: list[str], start_idx: int, start_pos: int) -> int | None:
    """Walk forward from ``lines[start_idx][start_pos:]`` tracking the
    running depth of ``()``/``[]``/``{}`` (string-literal- and line-comment-aware)
    until the depth returns to zero. Returns the line index containing
    the closing delimiter, or ``None`` if no balance by end-of-file. A start
    line with no delimiter at all is treated as the close (nothing to balance).

    Used by the wrapped-expression arm of the secrets check so multi-line
    wrappers like ``db_password = jsonencode({\\n  password = "leak"\\n})``
    are walked across newlines and scanned for inner string literals.
    """
    depth = 0
    started = False
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if _is_line_commented(line):
            continue
        offset = start_pos if idx == start_idx else 0
        depth, saw, closed = _balance_scan(_scrub_line(line)[offset:], depth)
        if saw:
            started = True
        if closed:
            return idx
        if not started:
            return idx  # no opener on the start line — nothing to balance
    return None


def _find_block_close_index(lines: list[str], start_idx: int, opener: str) -> int | None:
    """Return the line index containing the brace/bracket that closes the block.

    ``opener`` is ``"{"`` or ``"["``; matched closer is ``"}"`` / ``"]"``. The
    walk treats string literals and ``#`` / ``//`` line comments as inert
    (their contents don't change the brace count). Returns the matching line
    index, or ``None`` if no close is found by end-of-file.
    """
    closer = "}" if opener == "{" else "]"
    depth = 0
    for idx in range(start_idx, len(lines)):
        line = lines[idx]
        if _is_line_commented(line):
            continue
        depth, closed = _block_depth_scan(_scrub_line(line), depth, opener, closer)
        if closed:
            return idx
    return None


def _collect_tfvars_candidates(repo_root: Path, files: list[str] | None) -> list[Path]:
    """Resolve the ``*.tfvars`` files in scope: the subset of ``files`` that
    sits under ``platform/terraform/environments/`` when an explicit list is
    given, otherwise every ``*.tfvars`` file under that tree.
    """
    if files is not None:
        in_scope = [p for p in files if p.startswith(_TFVARS_SCOPE) and p.endswith(".tfvars")]
        return [repo_root / p for p in in_scope]
    candidates: list[Path] = []
    for scope in _TFVARS_SCOPE:
        base = repo_root / scope
        if not base.exists():
            continue
        candidates.extend(p for p in base.rglob("*.tfvars") if p.is_file() and not p.is_symlink())
    return candidates


def _is_public_material_name(var_name: str) -> bool:
    """``True`` for names ending in a public-material suffix (``*_public_key``,
    ``*_authorized_keys``, ``*_pubkey``, …) — material that is share-only by
    design, so a string literal there is not a leaked secret.
    """
    return any(var_name.endswith(suffix) for suffix in _NON_SECRET_NAME_SUFFIXES)


def _lines_have_string_literal(lines: list[str], start_idx: int, end_idx: int) -> bool:
    """``True`` if any line in ``lines[start_idx:end_idx + 1]`` carries a
    ``"..."`` literal once full-line comments are skipped and trailing
    ``#``/``//`` comment tails are stripped.
    """
    for idx in range(start_idx, end_idx + 1):
        inner = lines[idx]
        if _is_line_commented(inner):
            continue
        if _STRING_LITERAL_PATTERN.search(_strip_trailing_line_comment(inner)):
            return True
    return False


def _wrapped_rhs_has_literal(lines: list[str], idx: int, line: str, rhs: str) -> bool:
    """``True`` if a function-wrapped / expression RHS of a secret assignment
    materializes a string literal — scanning the RHS on the assignment line
    and, when it opens a balanced ``()``/``[]``/``{}`` that spans lines, the
    rest of the multi-line expression.
    """
    if _STRING_LITERAL_PATTERN.search(_strip_trailing_line_comment(rhs)):
        return True
    close_idx = _find_balanced_close_index(lines, idx, line.find("=") + 1)
    if close_idx is None or close_idx <= idx:
        return False
    return _lines_have_string_literal(lines, idx + 1, close_idx)


def _block_assignment_has_literal(lines: list[str], idx: int, opener: str) -> bool:
    """``True`` if the object/array block opened on ``lines[idx]`` carries a
    string literal somewhere between the opener and its matching close (an
    empty block, or one composed solely of var/local/data references, is
    acceptable). A block whose close is never found scans to end-of-file.
    """
    close_idx = _find_block_close_index(lines, idx, opener)
    end_idx = close_idx if close_idx is not None else len(lines) - 1
    return _lines_have_string_literal(lines, idx, end_idx)


def _flagged_secret_var(lines: list[str], idx: int) -> str | None:
    """Return the secret-bearing variable on ``lines[idx]`` that is assigned a
    plaintext string literal — directly, via a heredoc, via an object/array
    block, or wrapped in a function/expression — or ``None`` when the line is
    clean or the variable name is public material.
    """
    line = lines[idx]
    # Priority: a direct ``= "..."`` / heredoc literal, then an object/array
    # block, then any other RHS expression. ``_SECRET_ASSIGNMENT_PATTERN`` is
    # the catch-all, so it is consulted last.
    direct = _SECRET_VAR_PATTERN.match(line) or _SECRET_HEREDOC_PATTERN.match(line)
    block_match = _SECRET_BLOCK_OPEN_PATTERN.match(line)
    wrapped = _SECRET_ASSIGNMENT_PATTERN.match(line)
    match = direct or block_match or wrapped
    if match is None:
        return None
    var_name = match.group(1)
    if _is_public_material_name(var_name):
        return None
    if direct is not None:
        return var_name
    if block_match is not None:
        return var_name if _block_assignment_has_literal(lines, idx, block_match.group(2)) else None
    return var_name if _wrapped_rhs_has_literal(lines, idx, line, wrapped.group(2)) else None


def _scan_tfvars_file(path: Path, repo_root: Path) -> list[Violation]:
    """Scan one ``*.tfvars`` file for plaintext-secret assignments (ADR-004-R7).

    Block comments are spanned BEFORE line splitting so their contents
    (including any ``password = "..."`` examples) cannot trigger the regex;
    line numbers are preserved.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = _strip_hcl_comments(raw_text).splitlines()
    rel = _repo_relative(path, repo_root)
    violations: list[Violation] = []
    for idx, line in enumerate(lines):
        if _is_line_commented(line):
            continue
        var_name = _flagged_secret_var(lines, idx)
        if var_name is None:
            continue
        violations.append(
            Violation(
                "no-plaintext-secrets-in-tfvars",
                "ADR-004-R7",
                rel,
                f"Line {idx + 1}: {var_name!r} is assigned a "
                f"plaintext string literal; reference an out-of-band "
                f"secret store (Secrets Manager, SSM, environment) instead",
            )
        )
    return violations


def check_no_plaintext_secrets_in_tfvars(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid string literals on secret-bearing tfvars assignments (ADR-004-R7).

    Scans ``*.tfvars`` files committed under the Terraform environment and
    global trees and flags any line that assigns a quoted string to a variable
    whose name ends in ``password``, ``secret``, ``token``, ``key``,
    ``credentials``, ``credential``, ``authcode``, ``authcodes``, or
    ``pin_value``. Bare ``authcode`` / ``pin_value`` names are also flagged.
    Var/local/data references and empty strings are allowed
    (they don't materialize a credential in source). ``*.tfvars.example`` files
    and full-line comments are skipped.

    gitleaks catches high-entropy random strings; this is the complementary
    backstop for low-entropy committed credentials that gitleaks ignores
    (e.g. human-typed passwords with mixed case and a single digit suffix).
    """
    violations: list[Violation] = []
    for path in _collect_tfvars_candidates(repo_root, files):
        if path.exists():
            violations.extend(_scan_tfvars_file(path, repo_root))
    return violations


# Centralized blocked-path / blocked-name set for the
# `no-tracked-generated-artifacts` check (ADR-004-R8). Each entry is a
# pair: (root prefix under which the rule applies, predicate over the
# repo-relative path's basename). The roots are intentionally narrow so
# unrelated source files with overlapping names elsewhere in the repo
# are not flagged.
#
# Terraform plan outputs: `tfplan`, `plan.out`, and any `*.tfplan` /
# `*.tfplan.binary` under the AWS or GCP terraform environment trees.
# These are generated security-sensitive artifacts; they may carry
# state-derived values, resource addresses, and provider metadata and
# must not be tracked in source.
#
# Bootstrap license/authcode material: `authcodes` (and `*.authcodes`)
# under `temp/bootstrap/`. These are pre-staging outputs from local
# bootstrap workflows and must not be committed.
#
# Polaris range build output: every tracked file under
# `scenario-dev/polaris/build/`. That tree is generated/runtime material and
# can carry challenge-local keys, tokens, database access files, and baked
# runtime payloads. Source inputs live outside `build/`.
#
# Polaris AWS operator run outputs: machine-readable provisioning state and
# human-readable status/health reports under `scripts/polaris-aws-range/`.
# These are regenerated by orchestrate_provisioning.py and
# check_range_health.py during live events and may contain participant or
# infrastructure identifiers.
_GENERATED_ARTIFACT_ROOTS: tuple[str, ...] = (
    "platform/terraform/environments/",
    "platform/terraform/gcp/environments/",
    "scenario-dev/polaris/build/",
    "scripts/polaris-aws-range/",
    "temp/bootstrap/",
)


def _is_terraform_plan_artifact(basename: str) -> bool:
    """Return True for Terraform plan output filenames.

    Matches the canonical names produced by `terraform plan -out=...`
    workflows: `tfplan` and `tfplan.binary` (binary plan files) and
    `plan.out` (typical text dump). Also matches the `*.tfplan` and
    `*.tfplan.binary` families so per-environment names like
    `dev.tfplan` and `prod.tfplan.binary` are caught. Case-sensitive
    to avoid over-matching unrelated source filenames such as
    `terraform_planner.py`.
    """
    if basename in ("tfplan", "tfplan.binary", "plan.out"):
        return True
    return basename.endswith((".tfplan", ".tfplan.binary"))


def _is_bootstrap_authcode_artifact(basename: str) -> bool:
    """Return True for tracked bootstrap license/authcode filenames."""
    return basename == "authcodes" or basename.endswith(".authcodes")


def _is_polaris_operator_run_artifact(basename: str) -> bool:
    """Return True for tracked Polaris AWS operator run outputs."""
    return basename in (
        "provisioning_state.json",
        "provisioning_status.md",
        "health_report.md",
        "postprovision_status.md",
    )


def _generated_artifact_match(rel_path: str) -> bool:
    """Return True if a repo-relative path is a blocked generated artifact."""
    in_scope = any(rel_path.startswith(root) for root in _GENERATED_ARTIFACT_ROOTS)
    if not in_scope:
        return False
    basename = rel_path.rsplit("/", 1)[-1]
    if rel_path.startswith("platform/terraform/"):
        return _is_terraform_plan_artifact(basename)
    if rel_path.startswith("scenario-dev/polaris/build/"):
        return True
    if rel_path.startswith("scripts/polaris-aws-range/"):
        return _is_polaris_operator_run_artifact(basename)
    if rel_path.startswith("temp/bootstrap/"):
        return _is_bootstrap_authcode_artifact(basename)
    return False


def _iter_artifact_candidates(repo_root: Path) -> list[str]:
    """Return repo-relative paths of TRACKED files matching the policy.

    Codex review #1180 cycle 1 finding 1: the previous walk-the-
    filesystem implementation flagged any ignored local workspace
    file under the Terraform/temp roots, which would break
    `adr_guard --all --level ci` when a developer or earlier CI step
    generated an ephemeral `tfplan`. The contract is to block files
    that are tracked in source control (or staged for the next
    commit); files matched only by `.gitignore` are intentionally
    allowed. We delegate the source-controlled detection to
    `git ls-files`, which already considers both tracked + staged
    entries and is the canonical source for "what is in version
    control."

    A test that runs against a synthetic tmpdir (no `.git` present)
    falls back to the filesystem walk so the unit tests can build
    pseudo-trees without initializing a git repo. The fallback only
    triggers when there is no usable git index, never in real-repo
    use.
    """
    tracked = _git_tracked_under_roots(repo_root)
    if tracked is None:
        # No git index — synthetic test mode. Walk the filesystem.
        return _walk_filesystem_artifacts(repo_root)
    return [p for p in tracked if _generated_artifact_match(p)]


def _walk_filesystem_artifacts(repo_root: Path) -> list[str]:
    """Test-mode fallback: walk `_GENERATED_ARTIFACT_ROOTS` on disk
    and return matching repo-relative paths. Production code always
    reaches `_git_tracked_under_roots`; this branch is only exercised
    by unit tests building a synthetic tmpdir tree without a `.git`
    directory."""
    candidates: list[str] = []
    for root in _GENERATED_ARTIFACT_ROOTS:
        base = repo_root / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = _repo_relative(path, repo_root)
            if _generated_artifact_match(rel):
                candidates.append(rel)
    return candidates


def _git_tracked_under_roots(repo_root: Path) -> list[str] | None:
    """Return all tracked (and staged) repo-relative paths under
    `_GENERATED_ARTIFACT_ROOTS`, or `None` if `repo_root` is not a
    git working tree."""
    if not (repo_root / ".git").exists():
        return None
    cmd = [
        "git",
        "-C",
        str(repo_root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *_GENERATED_ARTIFACT_ROOTS,
    ]
    try:
        # `--cached` enumerates tracked files; `--others
        # --exclude-standard` adds untracked files NOT ignored by
        # gitignore — that captures `git add -f` candidates that
        # bypassed .gitignore and would otherwise be invisible to a
        # tracked-only check until they hit the index.
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.decode("utf-8", errors="replace")
    return [entry for entry in output.split("\0") if entry]


# Centralized scope for the `no-populated-secret-env-files` check
# (ADR-004-R9). Each entry is a repo-relative path prefix under which
# `*-secrets.env` files are scanned. Adding a future overlay (e.g.
# `platform/k8s/gcp/overlays/gcp-prod/`) is automatically covered;
# adding a new top-level location (e.g. a different cluster tree) is
# one entry here.
_SECRET_ENV_ROOTS: tuple[str, ...] = ("platform/k8s/",)

# Basename suffix that selects "secret env" files. Matched on the
# basename only so unrelated `*.env` files (config-bearing, not
# secret-bearing) are not scanned by this check.
_SECRET_ENV_SUFFIX = "-secrets.env"

# Fail-loud synthetic values that may appear as the RHS of an
# assignment in a tracked secret env file. The intent is that
# committed files render Kustomize / kube-linter / kubeconform
# successfully while making it obvious to anyone who deploys with the
# committed values that they have NOT supplied real secrets. Real
# values flow in at deploy time from GitHub Secrets, GCP Secret
# Manager, a gitignored local env file, or a deploy-time Kubernetes
# Secret.
#
# The allowlist is intentionally small and FIXED. Codex review cycle 3
# caught that an earlier `<...>` regex would accept any angle-bracket
# value (e.g. `DB_PASSWORD=<attacker-known-password>`) — a committer
# could wrap a real low-entropy credential in brackets, the guard
# would call it a placeholder, and Kustomize would treat the bracketed
# bytes as the literal Secret value at deploy. The bracket-syntax
# entries below are therefore an explicit fixed set, not a pattern.
# Broader synonyms must come through a deliberate ADR update, not
# ad-hoc growth.
_SECRET_ENV_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        # Bare placeholder tokens
        "REPLACE_AT_DEPLOY",
        "CHANGE_ME",
        "PLACEHOLDER",
        "EXAMPLE",
        # Equivalent bracketed forms (conventional in some example files);
        # the bracket allowlist is fixed, not pattern-based, to close the
        # angle-bracket bypass from cycle 3.
        "<replace-at-deploy>",
        "<replace_at_deploy>",
        "<REPLACE_AT_DEPLOY>",
        "<change-me>",
        "<change_me>",
        "<CHANGE_ME>",
        "<placeholder>",
        "<PLACEHOLDER>",
        "<example>",
        "<EXAMPLE>",
    }
)

def _is_secret_env_in_scope(rel_path: str) -> bool:
    """Return True for a repo-relative path that the secret-env check scans."""
    if not any(rel_path.startswith(root) for root in _SECRET_ENV_ROOTS):
        return False
    basename = rel_path.rsplit("/", 1)[-1]
    return basename.endswith(_SECRET_ENV_SUFFIX)


def _iter_secret_env_candidates(repo_root: Path) -> list[str]:
    """Return repo-relative paths of secret-env files in scope.

    Mirrors the tracked-only contract of
    `check_no_tracked_generated_artifacts`: prefer `git ls-files` so
    gitignored local-dev files (e.g. a developer's
    `platform-runtime-secrets.local.env`) are intentionally NOT
    scanned. Falls back to a filesystem walk only in the synthetic
    tmpdir test path where no `.git` directory exists.
    """
    tracked = _git_tracked_under_roots_for_secret_env(repo_root)
    if tracked is None:
        return _walk_filesystem_secret_env(repo_root)
    return [p for p in tracked if _is_secret_env_in_scope(p)]


def _git_tracked_under_roots_for_secret_env(repo_root: Path) -> list[str] | None:
    """Tracked + non-ignored repo-relative paths under the secret-env
    roots, or `None` if `repo_root` is not a git working tree."""
    if not (repo_root / ".git").exists():
        return None
    cmd = [
        "git",
        "-C",
        str(repo_root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        *_SECRET_ENV_ROOTS,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        # `git` unavailable or hung — fall back to filesystem walk so
        # the check still runs (synthetic-mode contract).
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.split(b"\x00")
    return [entry.decode("utf-8") for entry in raw if entry]


def _walk_filesystem_secret_env(repo_root: Path) -> list[str]:
    """Test-mode fallback: walk the configured secret-env roots."""
    candidates: list[str] = []
    for root in _SECRET_ENV_ROOTS:
        base = repo_root / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = _repo_relative(path, repo_root)
            if _is_secret_env_in_scope(rel):
                candidates.append(rel)
    return candidates


def _is_synthetic_placeholder(value: str) -> bool:
    """Return True if `value` is an allowed fail-loud placeholder.

    The allowlist is a fixed set (see `_SECRET_ENV_PLACEHOLDERS`).
    Pattern-based bracket matching was removed in cycle 3 because it
    accepted arbitrary `<...>` content, which would allow a committer
    to hide a real credential as `<attacker-known-password>` and have
    the guardrail pass.
    """
    stripped = value.strip()
    if stripped == "":
        return True
    return stripped in _SECRET_ENV_PLACEHOLDERS


def _scan_secret_env_file(abs_path: Path, rel_path: str) -> list[Violation]:
    """Return violations for any populated, non-placeholder line.

    Parsing rules:

    - A line whose first non-whitespace character is `#`, or that is
      blank after strip, is a comment / blank and is skipped.
    - Any other line MUST contain `=` and is parsed by splitting on
      the first `=`. The LHS is treated as the variable name verbatim
      (any shape — `KEY`, `db.password`, `api-token`, `export KEY`)
      so non-identifier-key shapes cannot bypass the value check.
    - Inline `# ...` is NOT a comment. Kustomize's
      `secretGenerator.envs` loader follows the Docker env_file
      format: `#` is a comment only when it is the first non-
      whitespace character on a line; mid-line `#` is part of the
      value. Treating mid-line `#` as a comment would create a
      bypass (`TOKEN=#real-secret` would normalize to empty and pass
      the placeholder check while the bytes remain in source).
    - A non-comment, non-blank line that does NOT contain `=` is
      flagged as malformed so a committed value smuggled in via a
      non-`=` shape (free text, YAML, etc.) cannot slip past the
      value check.

    The violation message names the line number, the variable shape,
    and the path; it never echoes the rejected value, per the
    preflight contract that validation reports paths and variable
    names only.
    """
    violations: list[Violation] = []
    try:
        text = abs_path.read_text(encoding="utf-8")
    except OSError:
        return violations
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        if "=" not in stripped_line:
            violations.append(
                Violation(
                    check="no-populated-secret-env-files",
                    rule_id="ADR-004-R9",
                    path=rel_path,
                    message=(
                        f"Tracked secret-env line {lineno} is not a "
                        "comment, blank line, or `KEY=value` "
                        "assignment. Use one of the allowed synthetic "
                        "placeholders (REPLACE_AT_DEPLOY, CHANGE_ME, "
                        "PLACEHOLDER, EXAMPLE, or <placeholder>) or "
                        "remove the line."
                    ),
                )
            )
            continue
        key, _, rhs = line.partition("=")
        var_name = key.strip()
        if _is_synthetic_placeholder(rhs):
            continue
        violations.append(
            Violation(
                check="no-populated-secret-env-files",
                rule_id="ADR-004-R9",
                path=rel_path,
                message=(
                    f"Tracked secret-env assignment `{var_name}` "
                    f"(line {lineno}) has a non-placeholder value. "
                    "Replace with an allowed synthetic placeholder "
                    "(REPLACE_AT_DEPLOY, CHANGE_ME, PLACEHOLDER, "
                    "EXAMPLE, or <placeholder>); real values must come "
                    "from GCP Secret Manager, a gitignored local env "
                    "file, or a deploy-time Kubernetes Secret."
                ),
            )
        )
    return violations


def check_no_populated_secret_env_files(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Forbid populated assignments in tracked `*-secrets.env` files (ADR-004-R9).

    Scans tracked `*-secrets.env` files under `_SECRET_ENV_ROOTS` (currently
    `platform/k8s/`). Allows comments, blank lines, empty assignments
    (`KEY=`), and a small synthetic-placeholder set. Anything else is
    flagged as a real value that must not ship in source.

    Reports violations with `rule_id="ADR-004-R9"`. Violation messages
    name the path and the variable name; they NEVER echo the rejected
    value. Mirrors `check_no_tracked_generated_artifacts` in using
    `git ls-files` for containment (so gitignored local-dev files are
    intentionally not scanned) with a filesystem-walk fallback for
    synthetic-tmpdir unit tests.
    """
    if files is not None:
        in_scope = sorted({p for p in files if _is_secret_env_in_scope(p)})
    else:
        in_scope = sorted(set(_iter_secret_env_candidates(repo_root)))
    violations: list[Violation] = []
    for rel in in_scope:
        abs_path = repo_root / rel
        if not abs_path.exists() or not abs_path.is_file():
            continue
        violations.extend(_scan_secret_env_file(abs_path, rel))
    return violations


def check_no_tracked_generated_artifacts(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Forbid tracked generated/sensitive artifacts (ADR-004-R8).

    Three artifact families are blocked, each scoped narrowly:

    - Terraform plan outputs (`tfplan`, `plan.out`, `*.tfplan`,
      `*.tfplan.binary`) under `platform/terraform/environments/` and
      `platform/terraform/gcp/environments/`. Plan files are generated
      security-sensitive artifacts: they may carry state-derived
      values, resource addresses, provider metadata, and deployment-
      specific operational details.
    - License / authcode bootstrap material (`authcodes`,
      `*.authcodes`) under `temp/bootstrap/`. These pre-staging
      outputs must not be tracked.
    - Polaris range build output under `scenario-dev/polaris/build/`.
      This is generated/runtime material, not source.

    The check fails closed at the staged-source boundary. It does NOT
    parse plan binaries or echo file content — the violation message
    names the repo-relative path and the remediation.
    """
    violations: list[Violation] = []
    if files is not None:
        in_scope = sorted({p for p in files if _generated_artifact_match(p)})
    else:
        in_scope = sorted(set(_iter_artifact_candidates(repo_root)))
    for rel in in_scope:
        violations.append(
            Violation(
                check="no-tracked-generated-artifacts",
                rule_id="ADR-004-R8",
                path=rel,
                message=(
                    "Generated/sensitive artifact must not be tracked in source. "
                    "Remove with `git rm` and ensure the path is covered by "
                    ".gitignore + the ADR-004-R8 guardrail."
                ),
            )
        )
    return violations


_DEPLOY_WORKFLOW_PATH = ".github/workflows/deploy.yml"
_CORE_WORKFLOW_PATH = ".github/workflows/_core.yml"
_RANGE_WORKFLOW_PATH = ".github/workflows/_range.yml"
_PLATFORM_WORKFLOW_PATH = ".github/workflows/_shifter-platform.yml"
_ADR_GUARD_SCRIPT_PATH = "scripts/adr_guard/adr_guard.py"
_PLAN_SCOPE_CHECK = "deploy-workflow-plan-scope"
_PLAN_SCOPE_RULE = "ADR-003-R2"
_TERRAFORM_PLAN_FILE = "tfplan"
_QUALITY_RELEVANT_OUTPUT = (
    "quality_relevant: ${{ steps.quality_non_docs.outputs.non_docs == 'true' || "
    "steps.quality_guardrails.outputs.guardrail_docs == 'true' }}"
)
_QUALITY_RELEVANT_CONDITION = "needs.changes.outputs.quality_relevant == 'true'"
_QUALITY_PREDICATE = "predicate-quantifier: every"
_QUALITY_NON_DOCS_REQUIRED_GLOBS = (
    "**",
    "!docs/**",
    "!**/*.md",
)
_QUALITY_GUARDRAIL_DOCS_REQUIRED_GLOBS = (
    ".github/pull_request_template.md",
    ".github/copilot-instructions.md",
    "docs/adr/**",
    "docs/technical/dev/adr-enforcement.md",
)
_PR_GATE_SKIPPED_QUALITY_GUARD = (
    '[ "$quality_result" = "skipped" ] && [ "$quality_relevant" != "false" ]'
)
_QUALITY_WORKFLOW_PATH = ".github/workflows/_quality.yml"
_SKIP_TESTS_LITERAL = "skip_tests: false"
_SKIP_TESTS_FORBIDDEN_MARKERS = (
    "[skip tests]",
    "[skip quality]",
    "Check for skip flags",
)
# Lint / architecture / security jobs in _quality.yml that must never be gated
# on inputs.skip_tests (ADR-003-R2 / issue #760).
_QUALITY_SKIP_TESTS_IMMUNE_JOB_SUFFIXES = ("-lint", "-lint-js", "-sast", "-arch")
_QUALITY_SKIP_TESTS_IMMUNE_JOB_NAMES = frozenset(
    {
        "adr-conformance",
        "workflow-lint",
        "terraform-lint",
        "security-iac",
        "security-k8s",
        "secrets-gitleaks",
        "k8s-lint",
        "k8s-schema",
        "mcp-lint",
    }
)
_QUALITY_ONLY_OUTPUT = "quality_only: ${{ steps.filter.outputs.quality_only }}"
_QUALITY_ONLY_REQUIRED_GLOBS = (
    "scripts/polaris-aws-range/**",
    "scenario-dev/polaris/tests/**",
)
_PORTAL_IMAGE_OUTPUT = "portal_image: ${{ steps.filter.outputs.portal_image }}"
_PORTAL_IMAGE_DEPLOY_CONDITION = "needs.changes.outputs.portal_image == 'true'"
_PORTAL_IMAGE_REQUIRED_GLOB = "shifter/shifter_platform/**"
_PORTAL_IMAGE_BUILD_INPUT = "inputs.portal_image_changes"
_PORTAL_DEPLOY_MODE_CHECK = "portal-deploy-mode-source-of-truth"
_PORTAL_DEPLOY_MODE_RULE = "ADR-003-R4"
_PORTAL_DEPLOY_HELPER_PATH = "scripts/portal_deploy/portal_deploy.py"
_PORTAL_DEV_OUTPUTS_PATH = "platform/terraform/environments/dev/portal/outputs.tf"
_PORTAL_PROD_OUTPUTS_PATH = "platform/terraform/environments/prod/portal/outputs.tf"


def _deploy_plan_scope_relevant(files: list[str] | None) -> bool:
    if files is None:
        return True
    relevant = {
        _DEPLOY_WORKFLOW_PATH,
        _CORE_WORKFLOW_PATH,
        _RANGE_WORKFLOW_PATH,
        _PLATFORM_WORKFLOW_PATH,
        _QUALITY_WORKFLOW_PATH,
        _ADR_GUARD_SCRIPT_PATH,
    }
    return any(path in relevant for path in files)


def _should_check_plan_scope_file(files: list[str] | None, path: str) -> bool:
    return files is None or path in files or _ADR_GUARD_SCRIPT_PATH in files


def _paths_filter_block(deploy_text: str, filter_name: str) -> list[str]:
    block: list[str] = []
    in_block = False
    block_indent: int | None = None
    for raw_line in deploy_text.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if stripped == f"{filter_name}:":
            in_block = True
            block_indent = indent
            continue
        if not in_block:
            continue
        if stripped and block_indent is not None and indent <= block_indent:
            break
        block.append(stripped)
    return block


def _workflow_job_block(workflow_text: str, job_name: str) -> list[str]:
    block: list[str] = []
    in_block = False
    for raw_line in workflow_text.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 2 and stripped == f"{job_name}:":
            in_block = True
            continue
        if in_block and stripped and indent == 2 and not stripped.startswith("- "):
            break
        if in_block:
            block.append(stripped)
    return block


def _block_contains_glob(block: list[str], glob: str) -> bool:
    return glob in _filter_globs(block)


def _filter_globs(block: list[str]) -> list[str]:
    globs: list[str] = []
    for line in block:
        if not line.startswith("- "):
            continue
        glob = line[2:].strip()
        if len(glob) >= 2 and glob[0] == glob[-1] and glob[0] in {"'", '"'}:
            glob = glob[1:-1]
        if glob:
            globs.append(glob)
    return globs


def _active_line_contains(block: list[str], needle: str) -> bool:
    return any(needle in line for line in block if not line.lstrip().startswith("#"))


def _extract_job_if(block: list[str]) -> str:
    """Return the ``if:`` expression for a stripped workflow job block."""
    active = [line for line in block if not line.lstrip().startswith("#")]
    for idx, line in enumerate(active):
        if not line.startswith("if:"):
            continue
        rest = line[3:].strip()
        if rest == "|":
            body: list[str] = []
            for follow in active[idx + 1 :]:
                if re.match(r"^[A-Za-z0-9_-]+:", follow):
                    break
                body.append(follow)
            return " ".join(body)
        return rest
    return ""


def _quality_job_is_skip_tests_immune(job_name: str) -> bool:
    if job_name in _QUALITY_SKIP_TESTS_IMMUNE_JOB_NAMES:
        return True
    return any(job_name.endswith(suffix) for suffix in _QUALITY_SKIP_TESTS_IMMUNE_JOB_SUFFIXES)


def _quality_workflow_job_names(quality_text: str) -> list[str]:
    names: list[str] = []
    in_jobs = False
    for raw_line in quality_text.splitlines():
        if raw_line.strip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if raw_line and not raw_line.startswith(" "):
            break
        match = re.match(r"^  ([a-z0-9_-]+):\s*$", raw_line)
        if match:
            names.append(match.group(1))
    return names


def _check_deploy_workflow_skip_tests_policy(deploy_text: str) -> list[Violation]:
    """ADR-003-R2: commit-message / dynamic test skips are not accepted."""
    violations: list[Violation] = []
    lowered = deploy_text.lower()
    for marker in _SKIP_TESTS_FORBIDDEN_MARKERS:
        if marker.lower() in lowered:
            violations.append(
                _plan_scope_violation(
                    _DEPLOY_WORKFLOW_PATH,
                    f"Commit-message or label-based test skips are not accepted; "
                    f"remove `{marker}` handling from the deploy workflow",
                )
            )
            break

    quality_block = _workflow_job_block(deploy_text, "quality")
    if not quality_block:
        return violations
    if not (
        _active_line_contains(quality_block, "_quality.yml")
        or _active_line_contains(quality_block, "./.github/workflows/_quality.yml")
    ):
        return violations
    if not _active_line_contains(quality_block, _SKIP_TESTS_LITERAL):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The Quality reusable-workflow call must pass "
                f"`{_SKIP_TESTS_LITERAL}` literally so protected-branch CI "
                "cannot bypass unit tests through commit-message flags",
            )
        )
    if _active_line_contains(quality_block, "skip_tests: ${{") or _active_line_contains(
        quality_block, "skip_tests:${{"
    ):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The Quality reusable-workflow call must not derive "
                "`skip_tests` from step outputs or commit-message parsing",
            )
        )
    return violations


def _check_quality_workflow_skip_tests_contract(quality_text: str) -> list[Violation]:
    """Architecture, lint, and security jobs must not honor ``inputs.skip_tests``."""
    violations: list[Violation] = []
    for job_name in _quality_workflow_job_names(quality_text):
        if not _quality_job_is_skip_tests_immune(job_name):
            continue
        block = _workflow_job_block(quality_text, job_name)
        if not block:
            continue
        if_expr = _extract_job_if(block)
        if "skip_tests" in if_expr:
            violations.append(
                _plan_scope_violation(
                    _QUALITY_WORKFLOW_PATH,
                    f"Job `{job_name}` must not be gated on `inputs.skip_tests`; "
                    "lint, architecture, and security checks run even when unit "
                    "tests are skipped",
                )
            )
    return violations


def _terraform_plan_has_lock_timeout(stripped_line: str) -> bool:
    if stripped_line.startswith("- run:"):
        command = stripped_line.split(":", 1)[1].strip()
    else:
        command = stripped_line
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens[:-1]):
        if token != "terraform" or tokens[index + 1] != "plan":
            continue
        plan_tokens: list[str] = []
        for plan_token in tokens[index + 2 :]:
            if plan_token in {"&&", "||", ";", "|"}:
                break
            plan_tokens.append(plan_token)
        return "-lock-timeout=5m" in plan_tokens
    return False


def _terraform_plan_writes_saved_plan(stripped_line: str) -> bool:
    if stripped_line.startswith("- run:"):
        command = stripped_line.split(":", 1)[1].strip()
    else:
        command = stripped_line
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens[:-1]):
        if token != "terraform" or tokens[index + 1] != "plan":
            continue
        plan_tokens: list[str] = []
        for plan_token in tokens[index + 2 :]:
            if plan_token in {"&&", "||", ";", "|"}:
                break
            plan_tokens.append(plan_token)
        if f"-out={_TERRAFORM_PLAN_FILE}" in plan_tokens:
            return True
        return any(
            plan_token == "-out"
            and next_index + 1 < len(plan_tokens)
            and plan_tokens[next_index + 1] == _TERRAFORM_PLAN_FILE
            for next_index, plan_token in enumerate(plan_tokens)
        )
    return False


def _terraform_apply_uses_saved_plan(stripped_line: str) -> bool:
    if stripped_line.startswith("- run:"):
        command = stripped_line.split(":", 1)[1].strip()
    else:
        command = stripped_line
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens[:-1]):
        if token != "terraform" or tokens[index + 1] != "apply":
            continue
        apply_tokens = tokens[index + 2 :]
        return (
            "-lock-timeout=5m" in apply_tokens
            and _TERRAFORM_PLAN_FILE in apply_tokens
            and "-auto-approve" not in apply_tokens
        )
    return False


def _line_removes_tfplan(stripped_line: str) -> bool:
    if _TERRAFORM_PLAN_FILE not in stripped_line:
        return False
    if stripped_line.startswith("- run:"):
        command = stripped_line.split(":", 1)[1].strip()
    else:
        command = stripped_line
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError:
        tokens = command.split()
    return "rm" in tokens and _TERRAFORM_PLAN_FILE in tokens


def _plan_scope_violation(path: str, message: str) -> Violation:
    return Violation(_PLAN_SCOPE_CHECK, _PLAN_SCOPE_RULE, path, message)


def _platform_app_source_globs(deploy_text: str) -> list[str]:
    platform_block = _paths_filter_block(deploy_text, "shifter_platform")
    return [
        glob
        for glob in _filter_globs(platform_block)
        if glob == "shifter/**" or glob.startswith("shifter/")
    ]


def _check_deploy_workflow_plan_routing(deploy_text: str) -> list[Violation]:
    violations: list[Violation] = []
    app_source_globs = _platform_app_source_globs(deploy_text)
    if app_source_globs:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "`shifter_platform` must not include app-source globs under `shifter/`; "
                f"found {', '.join(app_source_globs)}",
            )
        )

    changes_block = _workflow_job_block(deploy_text, "changes")
    quality_block = _workflow_job_block(deploy_text, "quality")
    pr_gate_block = _workflow_job_block(deploy_text, "pr-gate")
    non_docs_block = _paths_filter_block(deploy_text, "non_docs")
    guardrail_docs_block = _paths_filter_block(deploy_text, "guardrail_docs")

    if not _active_line_contains(changes_block, _QUALITY_RELEVANT_OUTPUT):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Quality routing must retain a `quality_relevant` changes-job output "
                "that combines the non-docs and guardrail-docs classifiers",
            )
        )
    elif not non_docs_block:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Quality routing must retain a `non_docs` filter so ordinary docs-only "
                "diffs are the only general Quality skip path",
            )
        )
    elif not _active_line_contains(changes_block, _QUALITY_PREDICATE):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The `non_docs` Quality classifier must use "
                f"`{_QUALITY_PREDICATE}` so exclusion globs are honored together",
            )
        )
    elif missing_non_doc_globs := [
        glob
        for glob in _QUALITY_NON_DOCS_REQUIRED_GLOBS
        if not _block_contains_glob(non_docs_block, glob)
    ]:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The `non_docs` Quality classifier is missing required docs-only "
                f"exclusion globs: {', '.join(missing_non_doc_globs)}",
            )
        )
    elif not guardrail_docs_block:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Quality routing must retain a `guardrail_docs` filter so ADR and "
                "enforcement-doc changes still run Quality",
            )
        )
    elif missing_guardrail_globs := [
        glob
        for glob in _QUALITY_GUARDRAIL_DOCS_REQUIRED_GLOBS
        if not _block_contains_glob(guardrail_docs_block, glob)
    ]:
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The `guardrail_docs` Quality classifier is missing required "
                f"guardrail paths: {', '.join(missing_guardrail_globs)}",
            )
        )
    elif not _active_line_contains(quality_block, _QUALITY_RELEVANT_CONDITION):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The Quality job must include "
                f"`{_QUALITY_RELEVANT_CONDITION}` so non-docs and guardrail-docs "
                "changes run Quality",
            )
        )
    elif not pr_gate_block or not _active_line_contains(
        pr_gate_block, _PR_GATE_SKIPPED_QUALITY_GUARD
    ):
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "PR Gate must reject skipped Quality unless `quality_relevant` is false, "
                "so skipped Quality is accepted only for ordinary docs-only changes",
            )
        )
    return violations


def _check_deploy_workflow_quality_only_routing(deploy_text: str) -> list[Violation]:
    """Require non-deploy test-support paths to remain categorized."""
    quality_only_block = _paths_filter_block(deploy_text, "quality_only")
    changes_block = _workflow_job_block(deploy_text, "changes")
    if not quality_only_block or not _active_line_contains(changes_block, _QUALITY_ONLY_OUTPUT):
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Non-deploy test-support changes must retain a `quality_only` "
                "filter/output; missing the filter or changes-job output",
            )
        ]

    missing_globs = [
        glob
        for glob in _QUALITY_ONLY_REQUIRED_GLOBS
        if not _block_contains_glob(quality_only_block, glob)
    ]
    if missing_globs:
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "`quality_only` must include "
                f"{', '.join(missing_globs)} so orphaned support test suites stay "
                "categorized without triggering deploy jobs",
            )
        ]
    return []


def _check_deploy_workflow_portal_image_routing(deploy_text: str) -> list[Violation]:
    """Require the portal-image deploy trigger restored by #913.

    Application-code changes must reach the portal build/deploy path through
    a dedicated `portal_image` filter, without widening the Terraform-scoped
    `shifter_platform` plan trigger.
    """
    portal_block = _paths_filter_block(deploy_text, "portal_image")
    changes_block = _workflow_job_block(deploy_text, "changes")
    platform_job_block = _workflow_job_block(deploy_text, "shifter_platform")
    if not portal_block or not _active_line_contains(changes_block, _PORTAL_IMAGE_OUTPUT):
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Portal application changes must retain a `portal_image` filter/output "
                "so app-only pushes still build and deploy the portal image (#913); "
                "missing the filter or changes-job output",
            )
        ]
    if not _block_contains_glob(portal_block, _PORTAL_IMAGE_REQUIRED_GLOB):
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                f"`portal_image` must include `{_PORTAL_IMAGE_REQUIRED_GLOB}` so portal "
                "application changes trigger the image build/deploy path",
            )
        ]
    if not _active_line_contains(platform_job_block, _PORTAL_IMAGE_DEPLOY_CONDITION):
        return [
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "The `shifter_platform` job must include "
                f"`{_PORTAL_IMAGE_DEPLOY_CONDITION}` so application-code pushes still "
                "invoke the portal build/deploy workflow",
            )
        ]
    return []


def _check_platform_build_portal_image_gate(platform_text: str) -> list[Violation]:
    """Require the platform build job to gate on the portal-image input (#913)."""
    build_block = _workflow_job_block(platform_text, "build")
    if not build_block or not _active_line_contains(build_block, _PORTAL_IMAGE_BUILD_INPUT):
        return [
            _plan_scope_violation(
                _PLATFORM_WORKFLOW_PATH,
                f"The `build` job must gate on `{_PORTAL_IMAGE_BUILD_INPUT}` so app-only "
                "changes build and deploy the portal image without running Terraform",
            )
        ]
    return []


def _check_deploy_concurrency_queues_apply_runs(deploy_text: str) -> list[Violation]:
    """Require deploy runs that can apply infrastructure to queue, not cancel.

    PR cancellation is still allowed because PR runs do not execute environment
    branch applies. A global `true` cancellation policy can kill Terraform
    mid-apply on `aws-dev` / `gcp-dev` pushes.
    """
    cancel_value: str | None = None
    for line in deploy_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped.startswith("cancel-in-progress:"):
            continue
        cancel_value = stripped.split(":", 1)[1].strip()
        break

    if cancel_value is None:
        return []

    normalized = cancel_value.strip()
    if normalized in {"false", "${{ false }}"}:
        return []
    if (
        "github.event_name == 'pull_request'" in normalized
        or 'github.event_name == "pull_request"' in normalized
    ):
        return []

    return [
        _plan_scope_violation(
            _DEPLOY_WORKFLOW_PATH,
            "Deploy workflow concurrency must queue env-branch apply runs instead "
            "of cancelling an in-flight Terraform apply; restrict cancellation to "
            "pull_request runs or set `cancel-in-progress: false`",
        )
    ]


def _check_terraform_plan_lock_timeout(workflow_text: str, path: str) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, line in enumerate(workflow_text.splitlines(), start=1):
        stripped = line.strip()
        if "terraform plan" not in stripped:
            continue
        if stripped.startswith(("#", "echo ")):
            continue
        if _terraform_plan_has_lock_timeout(stripped):
            continue
        violations.append(
            _plan_scope_violation(
                f"{path}:{lineno}",
                "AWS Terraform plan commands must include `-lock-timeout=5m` "
                "so legitimate concurrent plans wait for the state lock instead of failing",
            )
        )
    return violations


def _check_saved_plan_apply_contract(workflow_text: str, path: str) -> list[Violation]:
    """Require the apply job to create and consume a local saved Terraform plan."""
    violations: list[Violation] = []
    plan_block = _workflow_job_block(workflow_text, "plan")
    apply_block = _workflow_job_block(workflow_text, "apply")

    if not plan_block:
        return [
            _plan_scope_violation(
                path,
                "Terraform workflow is missing a `plan` job; ADR-003-R2 cannot verify "
                "saved-plan apply integrity",
            )
        ]
    if not apply_block:
        return [
            _plan_scope_violation(
                path,
                "Terraform workflow is missing an `apply` job; ADR-003-R2 cannot verify "
                "saved-plan apply integrity",
            )
        ]

    apply_plan_idx: int | None = None
    apply_command_idx: int | None = None
    for index, line in enumerate(apply_block):
        stripped = line.strip()
        if stripped.startswith(("#", "echo ")):
            continue
        if apply_plan_idx is None and "terraform plan" in stripped:
            apply_plan_idx = index
        if apply_command_idx is None and "terraform apply" in stripped:
            apply_command_idx = index

    if apply_plan_idx is None:
        violations.append(
            _plan_scope_violation(
                path,
                "The Terraform `apply` job must create a local saved Terraform plan "
                "(`terraform plan -lock-timeout=5m -out=tfplan`) immediately before "
                "applying, avoiding raw binary plan artifacts while ensuring apply "
                "executes a reviewed saved plan",
            )
        )
    elif not _terraform_plan_writes_saved_plan(apply_block[apply_plan_idx]):
        violations.append(
            _plan_scope_violation(
                path,
                "The Terraform `apply` job's local plan command must write `-out=tfplan` "
                "so the subsequent apply consumes a saved plan file",
            )
        )

    if apply_command_idx is None:
        violations.append(
            _plan_scope_violation(
                path,
                "The Terraform `apply` job must run `terraform apply -lock-timeout=5m "
                "tfplan` after creating the saved plan",
            )
        )
    elif apply_plan_idx is not None and apply_plan_idx > apply_command_idx:
        violations.append(
            _plan_scope_violation(
                path,
                "The Terraform `apply` job must create the saved `tfplan` before "
                "running `terraform apply`",
            )
        )

    for index, line in enumerate(apply_block):
        stripped = line.strip()
        if stripped.startswith(("#", "echo ")):
            continue
        if (
            apply_plan_idx is not None
            and apply_command_idx is not None
            and apply_plan_idx < index < apply_command_idx
            and _line_removes_tfplan(stripped)
        ):
            violations.append(
                _plan_scope_violation(
                    path,
                    "The Terraform `apply` job must not remove `tfplan` before applying; "
                    "Service Discovery checks and Terraform apply must consume the same "
                    "saved plan file",
                )
            )
        if "terraform apply" not in stripped:
            continue
        if _terraform_apply_uses_saved_plan(stripped):
            continue
        violations.append(
            _plan_scope_violation(
                path,
                "Terraform apply commands must apply the saved Terraform plan with "
                "`terraform apply -lock-timeout=5m tfplan`, not run a fresh "
                "`terraform apply -auto-approve`",
            )
        )
    return violations


def _check_terraform_workflow_integrity(workflow_text: str, path: str) -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(_check_terraform_plan_lock_timeout(workflow_text, path))
    violations.extend(_check_saved_plan_apply_contract(workflow_text, path))
    return violations


def check_deploy_workflow_plan_scope(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Keep AWS platform PR planning scoped to Terraform inputs."""
    if not _deploy_plan_scope_relevant(files):
        return []

    violations: list[Violation] = []
    deploy_path = repo_root / _DEPLOY_WORKFLOW_PATH
    core_path = repo_root / _CORE_WORKFLOW_PATH
    range_path = repo_root / _RANGE_WORKFLOW_PATH
    platform_path = repo_root / _PLATFORM_WORKFLOW_PATH

    check_deploy_and_platform = files is None or any(
        path in {_DEPLOY_WORKFLOW_PATH, _PLATFORM_WORKFLOW_PATH, _ADR_GUARD_SCRIPT_PATH}
        for path in files
    )

    if check_deploy_and_platform and not deploy_path.exists():
        violations.append(
            _plan_scope_violation(
                _DEPLOY_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R2 cannot verify platform plan routing",
            )
        )
    elif check_deploy_and_platform:
        deploy_text = deploy_path.read_text(encoding="utf-8")
        violations.extend(_check_deploy_concurrency_queues_apply_runs(deploy_text))
        violations.extend(_check_deploy_workflow_plan_routing(deploy_text))
        violations.extend(_check_deploy_workflow_quality_only_routing(deploy_text))
        violations.extend(_check_deploy_workflow_portal_image_routing(deploy_text))
        violations.extend(_check_deploy_workflow_skip_tests_policy(deploy_text))

    quality_path = repo_root / _QUALITY_WORKFLOW_PATH
    if files is None or _QUALITY_WORKFLOW_PATH in files or _ADR_GUARD_SCRIPT_PATH in files:
        if not quality_path.exists():
            violations.append(
                _plan_scope_violation(
                    _QUALITY_WORKFLOW_PATH,
                    "Required workflow is missing; ADR-003-R2 cannot verify "
                    "architecture/security independence from skip_tests",
                )
            )
        else:
            violations.extend(
                _check_quality_workflow_skip_tests_contract(
                    quality_path.read_text(encoding="utf-8")
                )
            )

    for path, workflow_path in (
        (_CORE_WORKFLOW_PATH, core_path),
        (_RANGE_WORKFLOW_PATH, range_path),
    ):
        if not _should_check_plan_scope_file(files, path):
            continue
        if not workflow_path.exists():
            violations.append(
                _plan_scope_violation(
                    path,
                    "Required workflow is missing; ADR-003-R2 cannot verify Terraform "
                    "lock-timeout and saved-plan apply integrity",
                )
            )
            continue
        violations.extend(
            _check_terraform_workflow_integrity(workflow_path.read_text(encoding="utf-8"), path)
        )

    if check_deploy_and_platform and not platform_path.exists():
        violations.append(
            _plan_scope_violation(
                _PLATFORM_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R2 cannot verify platform Terraform plan commands",
            )
        )
    elif check_deploy_and_platform:
        platform_text = platform_path.read_text(encoding="utf-8")
        violations.extend(_check_terraform_workflow_integrity(platform_text, _PLATFORM_WORKFLOW_PATH))
        violations.extend(_check_platform_build_portal_image_gate(platform_text))

    return violations


def _portal_deploy_mode_relevant(files: list[str] | None) -> bool:
    if files is None:
        return True
    relevant = {
        _PLATFORM_WORKFLOW_PATH,
        _PORTAL_DEPLOY_HELPER_PATH,
        _PORTAL_DEV_OUTPUTS_PATH,
        _PORTAL_PROD_OUTPUTS_PATH,
        _ADR_GUARD_SCRIPT_PATH,
    }
    return any(path in relevant for path in files)


def _portal_deploy_mode_violation(path: str, message: str) -> Violation:
    return Violation(_PORTAL_DEPLOY_MODE_CHECK, _PORTAL_DEPLOY_MODE_RULE, path, message)


def _check_portal_deploy_mode_workflow(platform_text: str) -> list[Violation]:
    violations: list[Violation] = []
    deploy_block = _workflow_job_block(platform_text, "deploy")
    if not deploy_block:
        return [
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "The platform deploy job is missing; ADR-003-R4 cannot verify portal "
                "deployment-mode source-of-truth handling",
            )
        ]
    if "AWS_PORTAL_ENABLE_AUTOSCALING" in platform_text:
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "`AWS_PORTAL_ENABLE_AUTOSCALING` must not drive the AWS portal deploy "
                "path; derive deployment mode from Terraform outputs instead",
            )
        )
    if not (
        _active_line_contains(deploy_block, _PORTAL_DEPLOY_HELPER_PATH)
        and _active_line_contains(deploy_block, "resolve-topology")
    ):
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "The deploy job must call `scripts/portal_deploy/portal_deploy.py "
                "resolve-topology` so the deploy path is derived from Terraform state",
            )
        )
    if not (
        _active_line_contains(deploy_block, "verify-asg-image")
        and _active_line_contains(deploy_block, "--image-digest")
    ):
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "The ASG deploy path must call `verify-asg-image` after instance refresh "
                "with `--image-digest` so every in-service instance is checked for the "
                "new portal image digest",
            )
        )
    return violations


def _check_portal_deploy_mode_outputs(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for outputs_path in (_PORTAL_DEV_OUTPUTS_PATH, _PORTAL_PROD_OUTPUTS_PATH):
        path = repo_root / outputs_path
        if not path.exists():
            violations.append(
                _portal_deploy_mode_violation(
                    outputs_path,
                    "Portal Terraform outputs are missing; ADR-003-R4 requires "
                    '`output "enable_autoscaling"` in each AWS portal environment',
                )
            )
            continue
        text = path.read_text(encoding="utf-8")
        if 'output "enable_autoscaling"' not in text:
            violations.append(
                _portal_deploy_mode_violation(
                    outputs_path,
                    'Portal Terraform outputs must expose `output "enable_autoscaling"` '
                    "so the deploy workflow reads the same mode Terraform applied",
                )
            )
    return violations


def _check_portal_deploy_helper(helper_text: str) -> list[Violation]:
    checks = (
        (
            "terraform output -json",
            "The portal deploy helper must read Terraform outputs, not a GitHub variable",
        ),
        (
            "len(running_instance_ids) != 1",
            "The portal deploy helper must fail unless single-instance mode finds exactly one "
            "running tagged instance",
        ),
        (
            "Reservations[].Instances[].InstanceId",
            "The portal deploy helper must query all matching running instances and must not "
            "pick `Reservations[0].Instances[0]`",
        ),
        (
            "describe-auto-scaling-groups",
            "The portal deploy helper must verify the Terraform ASG exists before choosing "
            "the ASG deploy path",
        ),
        (
            "send-command",
            "The portal deploy helper must use SSM to verify the running portal image digest "
            "on ASG instances",
        ),
        (
            "docker inspect",
            "The portal deploy helper must inspect the running portal container image during "
            "ASG verification",
        ),
        (
            "get-command-invocation",
            "The portal deploy helper must check each ASG instance's SSM verification result",
        ),
    )
    violations: list[Violation] = []
    for needle, message in checks:
        if needle not in helper_text:
            violations.append(
                _portal_deploy_mode_violation(_PORTAL_DEPLOY_HELPER_PATH, message)
            )
            break
    return violations


def check_portal_deploy_mode_source_of_truth(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Ensure the AWS portal deploy path is derived from Terraform state."""
    if not _portal_deploy_mode_relevant(files):
        return []

    violations: list[Violation] = []
    platform_path = repo_root / _PLATFORM_WORKFLOW_PATH
    helper_path = repo_root / _PORTAL_DEPLOY_HELPER_PATH

    if not platform_path.exists():
        violations.append(
            _portal_deploy_mode_violation(
                _PLATFORM_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R4 cannot verify portal "
                "deployment-mode source-of-truth handling",
            )
        )
    else:
        violations.extend(
            _check_portal_deploy_mode_workflow(platform_path.read_text(encoding="utf-8"))
        )

    violations.extend(_check_portal_deploy_mode_outputs(repo_root))

    if not helper_path.exists():
        violations.append(
            _portal_deploy_mode_violation(
                _PORTAL_DEPLOY_HELPER_PATH,
                "Portal deploy helper is missing; ADR-003-R4 requires a tested helper "
                "for Terraform-derived mode resolution and ASG image verification",
            )
        )
    else:
        violations.extend(_check_portal_deploy_helper(helper_path.read_text(encoding="utf-8")))

    return violations


_TFVARS_RENDER_CHECK = "aws-platform-renders-deploy-tfvars"
_TFVARS_RENDER_RULE = "ADR-011-R7"
# Jobs in `_shifter-platform.yml` that run Terraform against the portal root
# and therefore must render the deployment-owned override first.
_TFVARS_RENDER_JOBS = ("plan", "apply")
_LOCAL_AUTO_TFVARS = "local.auto.tfvars"
# `terraform` subcommands that consume variable values. `fmt`, `show`, and
# `output` do not, so the render step may legitimately sit after a `fmt` check.
_TF_CONSUMING_SUBCOMMANDS = ("init", "validate", "plan", "apply")


def _tfvars_render_violation(path: str, message: str) -> Violation:
    """Build an ADR-011-R7 violation for the deploy-tfvars-render check."""
    return Violation(_TFVARS_RENDER_CHECK, _TFVARS_RENDER_RULE, path, message)


def _is_terraform_consuming_command(stripped_line: str) -> bool:
    """True when the line runs a terraform subcommand that consumes variables."""
    if stripped_line.lstrip().startswith("#"):
        return False
    return any(f"terraform {sub}" in stripped_line for sub in _TF_CONSUMING_SUBCOMMANDS)


def _writes_local_auto_tfvars(stripped_line: str) -> bool:
    """True when the line redirects output *into* local.auto.tfvars.

    A line that merely names the file (e.g. the step's `name:`) is not
    proof of a render — only a write redirection (`> local.auto.tfvars`,
    including a path-prefixed `> dir/local.auto.tfvars`) counts, so the
    guard verifies executable behavior rather than a label.
    """
    if stripped_line.lstrip().startswith("#"):
        return False
    marker_pos = stripped_line.find(_LOCAL_AUTO_TFVARS)
    if marker_pos == -1:
        return False
    redirect_pos = stripped_line.find(">")
    return 0 <= redirect_pos < marker_pos


def _tfvars_render_violations_for_workflow(workflow_path: str, text: str) -> list[Violation]:
    """Return ADR-011-R7 violations for one reusable workflow file."""
    violations: list[Violation] = []
    for job in _TFVARS_RENDER_JOBS:
        block = _workflow_job_block(text, job)
        if not block:
            violations.append(
                _tfvars_render_violation(
                    workflow_path,
                    f"`{job}` job is missing; ADR-011-R7 expects it to render "
                    f"`{_LOCAL_AUTO_TFVARS}` before Terraform consumes variables",
                )
            )
            continue
        render_idx = next(
            (i for i, line in enumerate(block) if _writes_local_auto_tfvars(line)),
            None,
        )
        tf_idx = next(
            (i for i, line in enumerate(block) if _is_terraform_consuming_command(line)),
            None,
        )
        if render_idx is None:
            violations.append(
                _tfvars_render_violation(
                    workflow_path,
                    f"`{job}` job must render `{_LOCAL_AUTO_TFVARS}` from the deployment "
                    "secret (a step that writes the file, not merely names it) before "
                    "`terraform init/validate/plan/apply`, so the deploy never applies "
                    "the committed example.com baseline",
                )
            )
        elif tf_idx is not None and render_idx > tf_idx:
            violations.append(
                _tfvars_render_violation(
                    workflow_path,
                    f"`{job}` job renders `{_LOCAL_AUTO_TFVARS}` after a Terraform "
                    "command; the render must precede `terraform init/validate/plan/apply`",
                )
            )
    return violations


def check_platform_renders_deploy_tfvars(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Require AWS Terraform deploy jobs to render local.auto.tfvars first.

    The committed `terraform.tfvars` under `platform/terraform/environments/*`
    is an intentionally-broken `example.com` baseline. Each Terraform-running
    job in the AWS reusable workflows must render the deployment-owned override
    into a gitignored `local.auto.tfvars` before `terraform init/validate/plan/apply`
    consumes variables, so deploys never apply the baseline (ADR-011-R7).
    """
    workflow_paths = (_PLATFORM_WORKFLOW_PATH, _CORE_WORKFLOW_PATH, _RANGE_WORKFLOW_PATH)
    if files is not None and not any(
        path in {*workflow_paths, _ADR_GUARD_SCRIPT_PATH} for path in files
    ):
        return []

    violations: list[Violation] = []
    for workflow_path in workflow_paths:
        workflow_file = repo_root / workflow_path
        if not workflow_file.exists():
            continue
        violations.extend(
            _tfvars_render_violations_for_workflow(
                workflow_path,
                workflow_file.read_text(encoding="utf-8"),
            )
        )
    return violations


_FAIL_LOUD_CHECK = "deploy-verification-fail-loud"
_FAIL_LOUD_RULE = "ADR-003-R3"
_ENGINE_WORKFLOW_PATH = ".github/workflows/_shifter-engine.yml"
_GUAC_STABILIZE_STEP = "Wait for Guacamole ECS services to stabilize"
_ENGINE_TASKDEF_STEP = "Update ECS task definition"
# The engine ECS task-family skip is only acceptable behind this explicit
# bootstrap input (mirrors gcp_require_active_certificate); its presence in the
# step proves the skip is gated rather than unconditional.
_ENGINE_BOOTSTRAP_INPUT = "first_deploy"


def _fail_loud_relevant(files: list[str] | None) -> bool:
    if files is None:
        return True
    relevant = {
        _PLATFORM_WORKFLOW_PATH,
        _ENGINE_WORKFLOW_PATH,
        _DEPLOY_WORKFLOW_PATH,
        _ADR_GUARD_SCRIPT_PATH,
    }
    return any(path in relevant for path in files)


def _fail_loud_violation(path: str, message: str) -> Violation:
    return Violation(_FAIL_LOUD_CHECK, _FAIL_LOUD_RULE, path, message)


def _workflow_step_block(workflow_text: str, step_name: str) -> list[str]:
    """Return the raw lines of the named step, including its `run:` script.

    A step is the `- name: <step_name>` list item and every more-indented line
    beneath it, up to the next list item at the same indent or a dedent out of
    the step list. Returns [] when the step is not found.
    """
    block: list[str] = []
    in_block = False
    step_indent: int | None = None
    target = f"- name: {step_name}"
    for raw_line in workflow_text.splitlines():
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if not in_block:
            if stripped == target:
                in_block = True
                step_indent = indent
            continue
        # End the step at the next sibling list item or any dedent to/under it.
        if stripped and step_indent is not None and indent <= step_indent:
            break
        block.append(raw_line)
    return block


def _noncomment_contains(lines: list[str], needle: str) -> bool:
    return any(needle in line for line in lines if not line.lstrip().startswith("#"))


def _check_guacamole_timeout_fails(platform_text: str) -> list[Violation]:
    block = _workflow_step_block(platform_text, _GUAC_STABILIZE_STEP)
    if not block:
        return [
            _fail_loud_violation(
                _PLATFORM_WORKFLOW_PATH,
                f"`{_GUAC_STABILIZE_STEP}` step is missing; ADR-003-R3 cannot verify "
                "the Guacamole stabilization timeout fails the deploy",
            )
        ]
    # The stabilization poll is the last `while ... done` loop in the step; its
    # closing `done` separates the loop body from the timeout handler tail.
    done_idx = max(
        (i for i, line in enumerate(block) if line.strip() == "done"),
        default=None,
    )
    if done_idx is None:
        return [
            _fail_loud_violation(
                _PLATFORM_WORKFLOW_PATH,
                f"`{_GUAC_STABILIZE_STEP}` step has no polling loop; ADR-003-R3 expects "
                "a stabilization wait whose timeout fails the deploy",
            )
        ]
    tail = block[done_idx + 1 :]
    if not _noncomment_contains(tail, "exit 1") or _noncomment_contains(tail, "exit 0"):
        return [
            _fail_loud_violation(
                _PLATFORM_WORKFLOW_PATH,
                f"`{_GUAC_STABILIZE_STEP}` step must fail the deploy on stabilization "
                "timeout: the handler after the polling loop must `exit 1` (not warn and "
                "exit 0). Raise the timeout if first boot needs longer, but do not "
                "downgrade a timeout to a warning",
            )
        ]
    return []


def _check_engine_task_family_fails(engine_text: str) -> list[Violation]:
    block = _workflow_step_block(engine_text, _ENGINE_TASKDEF_STEP)
    if not block:
        return [
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                f"`{_ENGINE_TASKDEF_STEP}` step is missing; ADR-003-R3 cannot verify "
                "a missing engine task family fails the deploy",
            )
        ]
    violations: list[Violation] = []
    if not _noncomment_contains(block, "exit 1"):
        violations.append(
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                f"`{_ENGINE_TASKDEF_STEP}` step must `exit 1` when the ECS task "
                "definition family cannot be described, so a missing/typo'd family "
                "fails the deploy instead of skipping silently",
            )
        )
    if not _noncomment_contains(block, _ENGINE_BOOTSTRAP_INPUT):
        violations.append(
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                f"`{_ENGINE_TASKDEF_STEP}` step must gate any missing-family skip on the "
                f"explicit `{_ENGINE_BOOTSTRAP_INPUT}` bootstrap input; an unconditional "
                "`exit 0` skip lets a typo'd family skip every deploy forever",
            )
        )
    return violations


def check_deploy_verification_fail_loud(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Require deploy-verification steps to fail loud (ADR-003-R3).

    Two deploy steps must fail the run when the thing they verify did not
    happen, rather than warning and exiting 0:

    - `_shifter-platform.yml`'s Guacamole stabilization wait must `exit 1` on
      timeout (the FAILED circuit-breaker branch already does).
    - `_shifter-engine.yml`'s task-definition update must `exit 1` when the ECS
      task family cannot be described, with the only skip gated behind the
      explicit `first_deploy` bootstrap input.
    """
    if not _fail_loud_relevant(files):
        return []

    violations: list[Violation] = []
    platform_path = repo_root / _PLATFORM_WORKFLOW_PATH
    engine_path = repo_root / _ENGINE_WORKFLOW_PATH

    if not platform_path.exists():
        violations.append(
            _fail_loud_violation(
                _PLATFORM_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R3 cannot verify the Guacamole "
                "stabilization timeout fails the deploy",
            )
        )
    else:
        violations.extend(_check_guacamole_timeout_fails(platform_path.read_text(encoding="utf-8")))

    if not engine_path.exists():
        violations.append(
            _fail_loud_violation(
                _ENGINE_WORKFLOW_PATH,
                "Required workflow is missing; ADR-003-R3 cannot verify a missing engine "
                "task family fails the deploy",
            )
        )
    else:
        violations.extend(_check_engine_task_family_fails(engine_path.read_text(encoding="utf-8")))

    return violations


_BOUNDARY_MOCK_BASELINE_PATH = "scripts/adr_guard/boundary_mock_baseline.json"
_BOUNDARY_MOCK_CHECK_NAME = "boundary-mock-policy"
_BOUNDARY_MOCK_RULE = "ADR-019-R1"
_BOUNDARY_MOCK_BASE_REF_ENVS = ("ADR_GUARD_BASE_REF", "GITHUB_BASE_REF")
_BOUNDARY_MOCK_SKIP_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "staticfiles",
        "venv",
    }
)
_BOUNDARY_MOCK_BOUNDARY_SEGMENTS = frozenset(
    {
        "boto3",
        "botocore",
        "channels",
        "httpx",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
    }
)


def _boundary_mock_violation(path: str, message: str) -> Violation:
    """Shorthand for ADR-019-R1 violations."""
    return Violation(_BOUNDARY_MOCK_CHECK_NAME, _BOUNDARY_MOCK_RULE, path, message)


def _has_boundary_mock_skip_part(rel_path: str) -> bool:
    """Return True for files under local caches, virtualenvs, or generated trees."""
    return any(part in _BOUNDARY_MOCK_SKIP_PARTS for part in Path(rel_path).parts)


def _is_boundary_mock_test_path(rel_path: str) -> bool:
    """Return True for Python test files scanned by the boundary-mock policy."""
    if not rel_path.endswith(".py") or _has_boundary_mock_skip_part(rel_path):
        return False
    path = Path(rel_path)
    return "tests" in path.parts or path.name.startswith("test_") or path.name.endswith("_test.py")


def _git_tracked_python_files(repo_root: Path) -> list[str] | None:
    """Return tracked + non-ignored Python files, or None outside a git worktree."""
    if not (repo_root / ".git").exists():
        return None
    cmd = [
        "git",
        "-C",
        str(repo_root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "*.py",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [entry.decode("utf-8") for entry in result.stdout.split(b"\0") if entry]


def _walk_python_files(repo_root: Path) -> list[str]:
    """Filesystem fallback for synthetic tests without a git index."""
    files: list[str] = []
    for path in repo_root.rglob("*.py"):
        rel = _repo_relative(path, repo_root)
        if _has_boundary_mock_skip_part(rel):
            continue
        files.append(rel)
    return sorted(files)


def _iter_repo_python_files(repo_root: Path) -> list[str]:
    """Return repo-relative Python files from git when available."""
    tracked = _git_tracked_python_files(repo_root)
    if tracked is not None:
        return sorted({p for p in tracked if not _has_boundary_mock_skip_part(p)})
    return _walk_python_files(repo_root)


def _first_party_python_roots(repo_root: Path) -> set[str]:
    """Infer first-party import roots from tracked Python modules and packages."""
    roots: set[str] = set()
    for rel in _iter_repo_python_files(repo_root):
        if _is_boundary_mock_test_path(rel):
            continue
        path = Path(rel)
        if path.name == "__init__.py":
            root = path.parent.name
        else:
            root = path.stem
        if not root.isidentifier() or root in {"conftest", "tests"} or root.startswith("test_"):
            continue
        roots.add(root)
    return roots


def _boundary_mock_scope(repo_root: Path, files: list[str] | None) -> list[str]:
    """Select test files to scan for this invocation."""
    if files is None:
        return [p for p in _iter_repo_python_files(repo_root) if _is_boundary_mock_test_path(p)]

    touched = set(files)
    if _ADR_GUARD_PATH in touched or _BOUNDARY_MOCK_BASELINE_PATH in touched:
        return [p for p in _iter_repo_python_files(repo_root) if _is_boundary_mock_test_path(p)]

    return sorted({p for p in files if _is_boundary_mock_test_path(p)})


def _name_chain(node: ast.AST) -> str | None:
    """Return a dotted name for simple Name/Attribute AST nodes."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _name_chain(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return None


def _resolve_imported_name(name: str, imported_modules: dict[str, str]) -> str | None:
    """Resolve the leading segment of a dotted name through import aliases."""
    head, sep, tail = name.partition(".")
    resolved = imported_modules.get(head)
    if resolved is None:
        return name
    return f"{resolved}.{tail}" if sep else resolved


def _collect_mock_aliases(tree: ast.AST) -> tuple[set[str], set[str], dict[str, str]]:
    """Collect unittest.mock aliases and imported module aliases from a file."""
    patch_names: set[str] = set()
    mock_modules: set[str] = set()
    imported_modules: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                imported_modules[local] = alias.name
                if alias.name == "unittest":
                    mock_modules.add(f"{local}.mock")
                elif alias.name == "unittest.mock":
                    mock_modules.add(local if alias.asname else "unittest.mock")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                imported_modules[local] = f"{module}.{alias.name}" if module else alias.name
                if module == "unittest.mock" and alias.name == "patch":
                    patch_names.add(local)
                elif module == "unittest" and alias.name == "mock":
                    mock_modules.add(local)

    return patch_names, mock_modules, imported_modules


def _is_mock_patch_func(func: ast.AST, patch_names: set[str], mock_modules: set[str]) -> bool:
    """Return True for patch(...) or mock/mocker.patch(...)."""
    if isinstance(func, ast.Name):
        return func.id in patch_names
    if isinstance(func, ast.Attribute) and func.attr == "patch":
        base = _name_chain(func.value)
        return base in mock_modules or base == "mocker"
    return False


def _is_mock_patch_object_func(func: ast.AST, patch_names: set[str], mock_modules: set[str]) -> bool:
    """Return True for patch.object(...) or mock/mocker.patch.object(...)."""
    return isinstance(func, ast.Attribute) and func.attr == "object" and _is_mock_patch_func(
        func.value, patch_names, mock_modules
    )


def _patch_object_target(call: ast.Call, imported_modules: dict[str, str]) -> str | None:
    """Resolve patch.object(module_or_class, "name") into a dotted target when static."""
    if len(call.args) < 2:
        return None
    attr_arg = call.args[1]
    if not (isinstance(attr_arg, ast.Constant) and isinstance(attr_arg.value, str)):
        return None
    base = _name_chain(call.args[0])
    if base is None:
        return None
    resolved = _resolve_imported_name(base, imported_modules)
    if resolved is None:
        return None
    return f"{resolved}.{attr_arg.value}"


def _iter_boundary_patch_sites(repo_root: Path, rel_paths: list[str]) -> list[_BoundaryPatchSite]:
    """Statically discover string patch targets in selected test files."""
    sites: list[_BoundaryPatchSite] = []
    for rel in rel_paths:
        path = repo_root / rel
        if not path.exists() or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue

        patch_names, mock_modules, imported_modules = _collect_mock_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target: str | None = None
            if (
                _is_mock_patch_func(node.func, patch_names, mock_modules)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                target = node.args[0].value
            elif _is_mock_patch_object_func(node.func, patch_names, mock_modules):
                target = _patch_object_target(node, imported_modules)

            if target:
                sites.append(_BoundaryPatchSite(rel, node.lineno, target))
    return sites


def _is_allowed_boundary_patch_target(target: str) -> bool:
    """Return True for patch targets aimed at process/network/cloud boundaries."""
    parts = target.split(".")
    return any(part in _BOUNDARY_MOCK_BOUNDARY_SEGMENTS for part in parts[1:])


def _is_first_party_internal_patch_target(target: str, first_party_roots: set[str]) -> bool:
    """Return True for first-party targets that are not explicit boundary adapters."""
    root = target.split(".", 1)[0]
    return root in first_party_roots and not _is_allowed_boundary_patch_target(target)


def _parse_boundary_mock_baseline(raw: str, source: str) -> tuple[Counter[tuple[str, str]], Violation | None]:
    """Parse a boundary mock baseline payload into counts keyed by (path, target)."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return Counter(), _boundary_mock_violation(
            _BOUNDARY_MOCK_BASELINE_PATH,
            f"invalid baseline JSON in {source}: {exc}",
        )

    records = payload.get("allowed_internal_patch_counts") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return Counter(), _boundary_mock_violation(
            _BOUNDARY_MOCK_BASELINE_PATH,
            f"baseline in {source} must contain an allowed_internal_patch_counts list",
        )

    counts: Counter[tuple[str, str]] = Counter()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return Counter(), _boundary_mock_violation(
                _BOUNDARY_MOCK_BASELINE_PATH,
                f"baseline entry {index} in {source} must be an object",
            )
        rel = record.get("path")
        target = record.get("target")
        count = record.get("count")
        if not isinstance(rel, str) or not isinstance(target, str) or not isinstance(count, int) or count < 0:
            return Counter(), _boundary_mock_violation(
                _BOUNDARY_MOCK_BASELINE_PATH,
                f"baseline entry {index} in {source} must have string path/target "
                "and non-negative integer count",
            )
        counts[(rel, target)] += count
    return counts, None


def _load_boundary_mock_baseline(repo_root: Path) -> tuple[Counter[tuple[str, str]], Violation | None]:
    """Load the working-tree legacy internal patch baseline."""
    path = repo_root / _BOUNDARY_MOCK_BASELINE_PATH
    if not path.exists():
        return Counter(), _boundary_mock_violation(
            _BOUNDARY_MOCK_BASELINE_PATH,
            "boundary mock baseline is missing; generate it from current legacy internal patch counts",
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Counter(), _boundary_mock_violation(
            _BOUNDARY_MOCK_BASELINE_PATH,
            f"could not read baseline: {exc}",
        )

    return _parse_boundary_mock_baseline(raw, "working tree")


def _git_text(repo_root: Path, args: list[str]) -> str | None:
    """Run a read-only git command and return stdout when it succeeds."""
    if not (repo_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _boundary_mock_base_reference_candidates(repo_root: Path) -> list[str]:
    """Return base-branch commit-ish candidates for the baseline ratchet reference."""
    candidates: list[str] = []
    for env_name in _BOUNDARY_MOCK_BASE_REF_ENVS:
        base_ref = os.environ.get(env_name, "").strip()
        if not base_ref:
            continue
        candidates.append(base_ref)
        if base_ref.startswith("refs/heads/"):
            short = base_ref.removeprefix("refs/heads/")
            candidates.extend([f"origin/{short}", short])
        elif not base_ref.startswith("origin/") and not base_ref.startswith("refs/"):
            candidates.extend([f"origin/{base_ref}", base_ref])

    candidates.extend(["origin/dev", "dev", "origin/main", "main"])

    refs: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        merge_base = _git_text(repo_root, ["merge-base", "HEAD", candidate])
        if merge_base is None:
            continue
        ref = merge_base.strip()
        if ref and ref not in seen:
            refs.append(ref)
            seen.add(ref)

    return refs


def _boundary_mock_fallback_reference_candidates(repo_root: Path) -> list[str]:
    """Return fallback commit-ish candidates for shallow/synthetic repositories."""
    refs: list[str] = []
    seen: set[str] = set()
    for fallback in ("HEAD^1", "HEAD"):
        ref = _git_text(repo_root, ["rev-parse", "--verify", f"{fallback}^{{commit}}"])
        if ref is None:
            continue
        commit = ref.strip()
        if commit and commit not in seen:
            refs.append(commit)
            seen.add(commit)

    return refs


def _load_boundary_mock_reference_baseline(
    repo_root: Path,
) -> tuple[Counter[tuple[str, str]] | None, Violation | None]:
    """Load the baseline from the branch reference point, when one exists."""
    base_refs = _boundary_mock_base_reference_candidates(repo_root)
    for ref in base_refs:
        raw = _git_text(repo_root, ["show", f"{ref}:{_BOUNDARY_MOCK_BASELINE_PATH}"])
        if raw is None:
            continue
        return _parse_boundary_mock_baseline(raw, f"git reference {ref}")
    if base_refs:
        return None, None

    for ref in _boundary_mock_fallback_reference_candidates(repo_root):
        raw = _git_text(repo_root, ["show", f"{ref}:{_BOUNDARY_MOCK_BASELINE_PATH}"])
        if raw is None:
            continue
        return _parse_boundary_mock_baseline(raw, f"git reference {ref}")
    return None, None


def _check_boundary_mock_baseline_non_growth(
    repo_root: Path,
    current_baseline: Counter[tuple[str, str]],
) -> list[Violation]:
    """Fail any committed baseline allowance that grows against the reference baseline."""
    reference_baseline, reference_error = _load_boundary_mock_reference_baseline(repo_root)
    if reference_error is not None:
        return [reference_error]
    if reference_baseline is None:
        return []

    violations: list[Violation] = []
    for key, allowed in sorted(current_baseline.items()):
        reference_allowed = reference_baseline.get(key, 0)
        if allowed <= reference_allowed:
            continue
        rel, target = key
        violations.append(
            _boundary_mock_violation(
                _BOUNDARY_MOCK_BASELINE_PATH,
                f"baseline allowance for first-party internal patch target {target!r} in {rel} "
                f"grew from {reference_allowed} to {allowed}; baseline counts may only shrink "
                "without a dated ADR exception",
            )
        )
    return violations


def check_boundary_mock_policy(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Prevent net-new first-party internal mock patch targets in tests.

    Existing topology-coupled tests are represented by a committed baseline of
    ``(test file, patch target) -> count``. The check allows the baseline to
    shrink but fails any new internal target or count increase. Process,
    network, cloud SDK, and channel-layer transport patch targets remain
    allowed because they are real boundaries rather than first-party topology.
    """
    scan_files = _boundary_mock_scope(repo_root, files)
    if not scan_files:
        return []

    baseline, baseline_error = _load_boundary_mock_baseline(repo_root)
    if baseline_error is not None:
        return [baseline_error]

    violations = _check_boundary_mock_baseline_non_growth(repo_root, baseline)
    first_party_roots = _first_party_python_roots(repo_root)
    current: Counter[tuple[str, str]] = Counter()
    first_line: dict[tuple[str, str], int] = {}
    for site in _iter_boundary_patch_sites(repo_root, scan_files):
        if not _is_first_party_internal_patch_target(site.target, first_party_roots):
            continue
        key = (site.path, site.target)
        current[key] += 1
        first_line.setdefault(key, site.line)

    for key, found in sorted(current.items()):
        allowed = baseline.get(key, 0)
        if found <= allowed:
            continue
        rel, target = key
        violations.append(
            _boundary_mock_violation(
                f"{rel}:{first_line[key]}",
                f"first-party internal patch target {target!r} exceeds the legacy baseline "
                f"(allowed {allowed}, found {found}); patch a process/network/cloud boundary "
                "or assert observable behavior instead",
            )
        )
    return violations


# Canonical Python packages whose pyproject.toml must enforce the per-function
# complexity gate. Keyed off `.pre-commit-config.yaml` ruff hooks. Adding a new
# Python package with a ruff-pre-commit hook means adding it here too.
PYTHON_COMPLEXITY_GATE_PYPROJECTS = (
    "shifter/shifter_platform",
    "shifter/engine/provisioner",
    "shifter/packer",
    "shifter/installation",
    "scripts/bootstrap",
    "scripts/gcp",
    "scripts/check_layer_imports",
    "scripts/check_rds_pending_modifications",
    "scripts/assert_portal_inspection",
    "scripts/handle_sd_replacement",
    "uat/event-load-harness",
)

# Single repo-wide threshold for ruff's McCabe (C901) check. Equality, not <=.
# Ratchet edits update this constant and the production pyprojects in one PR;
# the constant exists so the ratchet point is searchable.
PYTHON_COMPLEXITY_THRESHOLD = 15

# Path constants referenced by violations and the consistency / reconciliation
# passes. Defined once so messages stay consistent and so SonarCloud's
# duplicate-literal rule is satisfied.
_PRECOMMIT_CONFIG_PATH = ".pre-commit-config.yaml"
_BACKLOG_DOC_PATH = "docs/adr/complexity-backlog.md"
_ADR_GUARD_PATH = "scripts/adr_guard/adr_guard.py"
_CHECK_NAME = "python-complexity-gate"
_RULE_R1 = "ADR-012-R1"
_RULE_R2 = "ADR-012-R2"

# Match `- id: ruff` (not `id: ruff-format`) anywhere in the line.
_RUFF_HOOK_ID_PATTERN = re.compile(r"^\s*-\s+id:\s+ruff\b(?!-)")
# Any new hook entry (used as a "we've moved on" marker by the state machine).
_HOOK_ID_PATTERN = re.compile(r"^\s*-\s+id:")
# `files: ^<path>/` line of a hook.
_HOOK_FILES_LINE_PATTERN = re.compile(r"^\s*files:\s*\^(\S+?)/\s*$")
# A line carrying a `# noqa: ...` exemption that includes C901 anywhere in
# the rules list (e.g. `# noqa: C901`, `# noqa: E501, C901`, `# noqa:C901`).
_NOQA_C901_PATTERN = re.compile(r"#\s*noqa\s*:\s*([A-Z0-9, ]+)")
# A bare `# noqa` with no code list. Ruff treats this as line-level
# suppression of ALL rules, which silently covers C901 on a def line — the
# scanner must detect this even though there is no explicit C901 code.
_NOQA_BARE_PATTERN = re.compile(r"#\s*noqa\b(?!\s*:)")
# `def NAME(` on the same line as a `# noqa: C901` is the repo convention
# (see docs/adr/complexity-backlog.md). Methods (`    def NAME(`) match too.
_DEF_NAME_PATTERN = re.compile(r"\bdef\s+(\w+)\s*\(")
# Source-file directories we never scan for noqa sites.
_NOQA_SCAN_SKIP_PARTS = frozenset({".venv", "venv", "__pycache__", "node_modules", "staticfiles", "migrations"})


def _selector_covers_c901(selector: str) -> bool:
    """Return True if a Ruff selector string would cover the ``C901`` rule.

    Ruff supports both exact codes (``C901``) and category prefixes
    (``C``, ``C9``, ``C90``) plus the wildcard ``ALL``. A selector covers
    ``C901`` whenever ``C901`` starts with it (after upper-casing). This is the
    same semantic ruff uses when expanding selectors against the rule set.
    """
    s = selector.strip().upper()
    if not s:
        return False
    if s == "ALL":
        return True
    return "C901".startswith(s)


def _any_selector_covers_c901(selectors: list[str]) -> bool:
    """Convenience: True iff any selector in ``selectors`` covers C901."""
    return any(_selector_covers_c901(s) for s in selectors)


def _classify_noqa_line(line: str) -> str | None:
    """Classify how a source line relates to C901 suppression.

    Returns:
    - ``"c901"`` — explicit ``# noqa: C901`` (alone or alongside other codes).
    - ``"<noqa-without-def>"`` — explicit ``# noqa: C901`` but no same-line def.
    - ``"<bare-noqa>"`` — bare ``# noqa`` (no code list) on a def line.
    - ``None`` — line does not affect C901.

    The two sentinel strings match the sentinel function names used in
    :func:`_scan_noqa_c901_sites` so the caller can route them straight to
    :func:`_classify_sentinel_noqa`.
    """
    coded_match = _NOQA_C901_PATTERN.search(line)
    def_match = _DEF_NAME_PATTERN.search(line)
    if coded_match:
        codes = {c.strip() for c in coded_match.group(1).split(",")}
        if "C901" not in codes:
            return None
        return "c901" if def_match else "<noqa-without-def>"
    if _NOQA_BARE_PATTERN.search(line) and def_match:
        return "<bare-noqa>"
    return None


def _scan_file_for_noqa(path: Path, relpath: str, sites: dict[tuple[str, str], tuple[str, int]]) -> None:
    """Scan one source file and record any C901-affecting noqa sites."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    for lineno, line in enumerate(lines, start=1):
        classification = _classify_noqa_line(line)
        if classification is None:
            continue
        if classification == "c901":
            # def_match is guaranteed by the "c901" branch in _classify_noqa_line.
            def_match = _DEF_NAME_PATTERN.search(line)
            assert def_match is not None
            sites[(relpath, def_match.group(1))] = (line.strip(), lineno)
        else:
            sites[(relpath, classification)] = (line.strip(), lineno)


def _scan_noqa_c901_sites(repo_root: Path) -> dict[tuple[str, str], tuple[str, int]]:
    """Walk canonical packages for noqa lines that suppress C901.

    Returns a mapping ``(file_relpath, function_name) -> (line_text, line_no)``.
    The line text/number are surfaced so violations can cite the source.

    Recognized exemption shapes on a ``def NAME(`` line:
    - ``# noqa: ..., C901, ...`` — explicit C901 code list (the repo convention).
    - ``# noqa`` (bare, no code list) — ruff suppresses every rule on the line,
      including C901. The scanner records this under the sentinel function name
      ``"<bare-noqa>"`` so the caller can emit a "use explicit codes" violation.

    Lines that carry ``# noqa: C901`` but no same-line ``def NAME(`` are recorded
    under ``"<noqa-without-def>"`` so the caller can emit a wrong-placement
    violation.
    """
    sites: dict[tuple[str, str], tuple[str, int]] = {}
    for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS:
        root = repo_root / pkg
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in _NOQA_SCAN_SKIP_PARTS for part in path.parts):
                continue
            relpath = path.resolve().relative_to(repo_root.resolve()).as_posix()
            _scan_file_for_noqa(path, relpath, sites)
    return sites


def _parse_complexity_backlog(repo_root: Path) -> set[tuple[str, str]] | None:
    """Parse the ADR-012 backlog doc into a set of ``(file, function)`` pairs.

    Returns ``None`` if the doc is missing (the caller emits a dedicated
    "missing backlog" violation). Empty backlog returns an empty set.

    Implementation: cell-by-cell split on ``|`` rather than a multi-quantifier
    regex. Linear in input size with no backtracking surface.
    """
    path = repo_root / _BACKLOG_DOC_PATH
    if not path.exists():
        return None
    entries: set[tuple[str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")]
        # A markdown table row has empty leading/trailing cells. The required
        # leading columns are `<pkg>|<file>|<fn>|<complexity>`; downstream
        # columns (tracking issue, owner, etc.) are accepted as long as the
        # leading shape is intact.
        if len(cells) < 6 or cells[0] or cells[-1]:
            continue
        _pkg, file_cell, fn_cell, comp_cell = cells[1], cells[2], cells[3], cells[4]
        if not (file_cell.startswith("`") and file_cell.endswith("`")):
            continue
        if not (fn_cell.startswith("`") and fn_cell.endswith("`")):
            continue
        if not comp_cell.isdigit():
            continue
        entries.add((file_cell.strip("`"), fn_cell.strip("`")))
    return entries


def _ruff_hook_paths_from_precommit(repo_root: Path) -> set[str] | None:
    """Return package paths covered by `id: ruff` hooks in .pre-commit-config.yaml.

    Returns ``None`` if the file is missing (synthetic test fixtures may omit
    it). Returns a set of path strings without leading ``^`` or trailing ``/``.

    Implementation: a simple line-by-line state machine, not a single multi-line
    regex. Avoids nested quantifiers (and the ReDoS-style backtracking risk
    SonarCloud's ``python:S5852`` would flag) and reads cleanly: a hook entry
    with ``id: ruff`` arms the state, and the next ``files:`` line emits the
    captured path.
    """
    config_path = repo_root / _PRECOMMIT_CONFIG_PATH
    if not config_path.exists():
        return None
    paths: set[str] = set()
    armed = False
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if _RUFF_HOOK_ID_PATTERN.match(line):
            armed = True
            continue
        if armed:
            files_match = _HOOK_FILES_LINE_PATTERN.match(line)
            if files_match:
                paths.add(files_match.group(1))
                armed = False
            elif _HOOK_ID_PATTERN.match(line):
                # A new hook started before we saw `files:`; disarm but
                # don't lose a fresh `id: ruff` line that may be this one.
                armed = bool(_RUFF_HOOK_ID_PATTERN.match(line))
    return paths


def _is_change_relevant(files: list[str] | None) -> bool:
    """Return True if the file list (``--files`` / ``--changed``) requires the check.

    The complexity gate runs unconditionally on ``--all`` (``files is None``).
    For targeted runs, only changes that could affect the gate are relevant:
    canonical pyprojects, ``.pre-commit-config.yaml``, the backlog doc,
    ``scripts/adr_guard/adr_guard.py`` (where the constants live), or any
    ``.py`` file under one of the canonical packages.
    """
    if files is None:
        return True
    canonical_paths = {f"{pkg}/pyproject.toml" for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS}
    fixed_relevant = canonical_paths | {
        _PRECOMMIT_CONFIG_PATH,
        _BACKLOG_DOC_PATH,
        _ADR_GUARD_PATH,
    }
    touched = set(files)
    if touched & fixed_relevant:
        return True
    return any(
        f.endswith(".py") and any(f.startswith(f"{pkg}/") for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS) for f in touched
    )


def _violation_r1(path: str, message: str) -> Violation:
    """Shorthand for an ADR-012-R1 violation under this check."""
    return Violation(_CHECK_NAME, _RULE_R1, path, message)


def _violation_r2(path: str, message: str) -> Violation:
    """Shorthand for an ADR-012-R2 violation under this check."""
    return Violation(_CHECK_NAME, _RULE_R2, path, message)


def _load_lint_section(path: Path) -> tuple[dict, Violation | None]:
    """Read a pyproject.toml and return its ``[tool.ruff.lint]`` mapping.

    Returns ``({}, Violation)`` on TOML decode errors so the caller can record
    the failure and continue to the next package. The relative path is derived
    from ``path``'s last two components (``<pkg>/pyproject.toml``).
    """
    relative = f"{path.parent.name}/{path.name}" if path.parent.name else path.name
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        return {}, _violation_r1(relative, f"pyproject.toml is not valid TOML: {exc}")
    lint = data.get("tool", {}).get("ruff", {}).get("lint", {})
    return lint, None


def _check_select(lint: dict, relative: str) -> list[Violation]:
    """C901 must be covered by ``select`` or ``extend-select``."""
    if _any_selector_covers_c901(lint.get("select", [])) or _any_selector_covers_c901(lint.get("extend-select", [])):
        return []
    return [
        _violation_r1(
            relative,
            '[tool.ruff.lint].select must enable "C901" (per-function complexity gate)',
        )
    ]


def _check_ignore_field(lint: dict, field: str, relative: str) -> list[Violation]:
    """``ignore`` / ``extend-ignore`` must not suppress C901 by any prefix."""
    covers = [s for s in lint.get(field, []) if _selector_covers_c901(s)]
    if not covers:
        return []
    return [
        _violation_r1(
            relative,
            f'[tool.ruff.lint].{field} must not suppress "C901" (selectors that cover it: {sorted(covers)})',
        )
    ]


def _check_per_file_ignores(lint: dict, relative: str) -> list[Violation]:
    """``per-file-ignores`` must not exempt C901 from any glob."""
    per_file_ignores = lint.get("per-file-ignores", {})
    broad = sorted(glob for glob, rules in per_file_ignores.items() if any(_selector_covers_c901(r) for r in rules))
    if not broad:
        return []
    return [
        _violation_r1(
            relative,
            '[tool.ruff.lint.per-file-ignores] must not suppress "C901" '
            f"(globs with covering selectors: {broad}); use per-function "
            "`# noqa: C901` instead",
        )
    ]


def _check_max_complexity(lint: dict, relative: str) -> list[Violation]:
    """``mccabe.max-complexity`` must equal the repo-wide threshold."""
    mccabe = lint.get("mccabe", {})
    if "max-complexity" not in mccabe:
        return [
            _violation_r1(
                relative,
                f"[tool.ruff.lint.mccabe].max-complexity must be set to {PYTHON_COMPLEXITY_THRESHOLD}",
            )
        ]
    if mccabe["max-complexity"] != PYTHON_COMPLEXITY_THRESHOLD:
        return [
            _violation_r1(
                relative,
                "[tool.ruff.lint.mccabe].max-complexity must equal "
                f"{PYTHON_COMPLEXITY_THRESHOLD} (got {mccabe['max-complexity']})",
            )
        ]
    return []


def _check_canonical_pyproject(pkg: str, repo_root: Path) -> list[Violation]:
    """Run all per-package pyproject checks for one canonical package."""
    relative = f"{pkg}/pyproject.toml"
    path = repo_root / pkg / "pyproject.toml"
    if not path.exists():
        return [
            _violation_r1(
                relative,
                f"missing pyproject.toml for canonical Python package {pkg}",
            )
        ]
    lint, decode_violation = _load_lint_section(path)
    if decode_violation is not None:
        return [decode_violation]
    return [
        *_check_select(lint, relative),
        *_check_ignore_field(lint, "ignore", relative),
        *_check_ignore_field(lint, "extend-ignore", relative),
        *_check_per_file_ignores(lint, relative),
        *_check_max_complexity(lint, relative),
    ]


def _check_precommit_consistency(repo_root: Path) -> list[Violation]:
    """Cross-check the constant against ``.pre-commit-config.yaml`` ruff hooks.

    Skips silently when the config file is missing (synthetic test fixtures
    legitimately omit it).
    """
    hook_paths = _ruff_hook_paths_from_precommit(repo_root)
    if hook_paths is None:
        return []
    constant = set(PYTHON_COMPLEXITY_GATE_PYPROJECTS)
    violations: list[Violation] = []
    for missing in sorted(hook_paths - constant):
        violations.append(
            _violation_r1(
                _PRECOMMIT_CONFIG_PATH,
                f"ruff pre-commit hook covers {missing!r} but it is not in "
                "PYTHON_COMPLEXITY_GATE_PYPROJECTS; add it or remove the hook",
            )
        )
    for stale in sorted(constant - hook_paths):
        violations.append(
            _violation_r1(
                _ADR_GUARD_PATH,
                f"PYTHON_COMPLEXITY_GATE_PYPROJECTS includes {stale!r} but no "
                "matching `id: ruff` hook exists in .pre-commit-config.yaml",
            )
        )
    return violations


def _classify_sentinel_noqa(file_: str, func: str, line_text: str, lineno: int) -> Violation | None:
    """Return a violation for sentinel noqa entries (wrong placement / bare)."""
    if func == "<noqa-without-def>":
        return _violation_r2(
            f"{file_}:{lineno}",
            f"`# noqa: C901` must be on the `def NAME(` line, not {line_text!r}",
        )
    if func == "<bare-noqa>":
        return _violation_r2(
            f"{file_}:{lineno}",
            "bare `# noqa` on a `def` line is forbidden — it silently "
            "suppresses C901; use an explicit code list (e.g. `# noqa: C901`) "
            "and add a backlog row",
        )
    return None


def _check_backlog_reconciliation(repo_root: Path) -> list[Violation]:
    """Compare in-source ``# noqa: C901`` sites against the ADR-012 backlog."""
    backlog = _parse_complexity_backlog(repo_root)
    if backlog is None:
        return [
            _violation_r2(
                _BACKLOG_DOC_PATH,
                "ADR-012 backlog doc is missing; the reconciliation gate cannot operate without it",
            )
        ]

    violations: list[Violation] = []
    noqa_sites = _scan_noqa_c901_sites(repo_root)
    # Sentinels first so authors get the clearer hint before the set-diff one.
    for (file_, func), (line_text, lineno) in sorted(noqa_sites.items()):
        sentinel = _classify_sentinel_noqa(file_, func, line_text, lineno)
        if sentinel is not None:
            violations.append(sentinel)

    # The keys of noqa_sites are already (file, func) tuples; filter on the
    # function-name component without redundant unpacking-on-iteration.
    noqa_pairs = {key for key in noqa_sites if not key[1].startswith("<")}
    for file_, func in sorted(noqa_pairs - backlog):
        _line_text, lineno = noqa_sites[(file_, func)]
        violations.append(
            _violation_r2(
                f"{file_}:{lineno}",
                f"unauthorized `# noqa: C901` exemption on `{func}` — add a row "
                f"to {_BACKLOG_DOC_PATH} or refactor the function below the threshold",
            )
        )
    for file_, func in sorted(backlog - noqa_pairs):
        violations.append(
            _violation_r2(
                _BACKLOG_DOC_PATH,
                f"stale backlog row for `{file_}::{func}` — no matching "
                "`# noqa: C901` exists in source; remove the row",
            )
        )
    return violations


def check_python_complexity_gate(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Enforce ADR-012-R1 / R2: per-package ruff config + backlog reconciliation.

    Three layers, applied independently:

    1. **Per-package pyproject.toml checks.** For each canonical package, verify
       that C901 is enabled (``select`` / ``extend-select`` with prefix
       semantics), not suppressed via ``ignore`` / ``extend-ignore`` /
       ``per-file-ignores``, and that ``mccabe.max-complexity`` equals
       :data:`PYTHON_COMPLEXITY_THRESHOLD`.
    2. **Pre-commit consistency.** ``PYTHON_COMPLEXITY_GATE_PYPROJECTS`` must
       match the ``id: ruff`` hook working directories in
       ``.pre-commit-config.yaml`` (in both directions).
    3. **Backlog reconciliation.** Every ``# noqa: C901`` in source must map
       1:1 to a row in ``docs/adr/complexity-backlog.md``; bare ``# noqa`` on
       a def line and ``# noqa: C901`` on a non-def line are explicit errors.

    This is a config-shape and reconciliation validator only. Computing
    per-function complexity is Ruff's job; this check is the structural
    backstop against silent gate removal and untracked exemptions.

    When ``files`` is supplied, the check is a no-op unless one of the relevant
    surfaces is in the change set (see :func:`_is_change_relevant`).
    """
    if not _is_change_relevant(files):
        return []
    violations: list[Violation] = []
    for pkg in PYTHON_COMPLEXITY_GATE_PYPROJECTS:
        violations.extend(_check_canonical_pyproject(pkg, repo_root))
    violations.extend(_check_precommit_consistency(repo_root))
    violations.extend(_check_backlog_reconciliation(repo_root))
    return violations


# ===========================================================================
# Deploy control-plane model + checks (ADR-003)
#
# The single workflow-as-data model for the deploy pipeline: it reads
# deploy.yml and the reusable deploy workflows as YAML and evaluates their
# `if:` gates, branch/event routing, and change filters semantically. The
# ADR-003-R5 runner-exposure check below runs on it as a hard gate; the
# consolidated test suite (scripts/adr_guard/tests/test_deploy_workflow.py)
# exercises the same model for the #781 upstream-gating, #892 branch/event
# matrix, and #913 change-filter invariants. No cloud calls, no Actions
# execution - only literal event/branch strings ever reach the env script.
# ===========================================================================
_ENGINE_WORKFLOW_PATH = ".github/workflows/_shifter-engine.yml"
_GCP_DEV_WORKFLOW_PATH = ".github/workflows/_gcp-dev.yml"
_DW_REUSABLE_WORKFLOW_PATHS = (
    _CORE_WORKFLOW_PATH,
    _RANGE_WORKFLOW_PATH,
    _ENGINE_WORKFLOW_PATH,
    _PLATFORM_WORKFLOW_PATH,
    _GCP_DEV_WORKFLOW_PATH,
)
_DW_RESULT_REF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.result")
_DW_EXPR_TOKEN = re.compile(
    r"""\s+
        |(?P<str>'[^']*')
        |(?P<op>==|!=|&&|\|\||!|\(|\))
        |(?P<ident>[A-Za-z0-9_.\-]+)""",
    re.VERBOSE,
)


class _DwShapeError(Exception):
    """A deploy workflow is missing a structurally-required key.

    Raised instead of returning a default so the model fails closed: an absent
    job, filter, ``needs``, or ``if`` block is an error, never a silent
    "not applicable".
    """


class _DwExprError(_DwShapeError):
    """An ``if:`` expression used a construct the constrained evaluator rejects."""


def _dw_load_workflow(repo_root: Path, rel: str) -> dict:
    """Load a workflow as a dict, normalizing the YAML 1.1 ``on:`` key.

    PyYAML resolves the bare word ``on`` to the Python boolean ``True``; map it
    back to the string ``"on"`` so callers can read triggers normally.
    """
    import yaml  # local import: keeps PyYAML optional for non-deploy checks

    path = repo_root / rel
    if not path.is_file():
        raise _DwShapeError(f"workflow not found: {rel}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise _DwShapeError(f"{rel}: top-level YAML is not a mapping")
    if True in data:  # bare `on:` parsed as boolean True under YAML 1.1
        data["on"] = data.pop(True)
    return data


def _dw_jobs(wf: dict, name: str = "<workflow>") -> dict:
    js = wf.get("jobs")
    if not isinstance(js, dict) or not js:
        raise _DwShapeError(f"{name}: missing or empty 'jobs' mapping")
    return js


def _dw_get_job(wf: dict, job_id: str, name: str = "<workflow>") -> dict:
    js = _dw_jobs(wf, name)
    if job_id not in js:
        raise _DwShapeError(f"{name}: job '{job_id}' not found")
    return js[job_id]


def _dw_normalize_expr(expr) -> str:
    """Collapse whitespace (incl. block-scalar newlines) to single spaces."""
    return " ".join(str(expr or "").split())


def _dw_job_if(job: dict) -> str:
    return _dw_normalize_expr(job.get("if", ""))


def _dw_runs_on(job: dict):
    return job.get("runs-on")


# Runner labels the ADR-003-R5 exposure check treats as self-hosted-class. A
# GCP-native runner (issue #1546) registers with `--no-default-labels` + a custom
# label, so a job selecting it never carries the literal `self-hosted` label;
# without this set the exposure check would skip that job and leave a
# pull_request-reachability blind spot when GCP-dev CI is cut over to its own
# runner. New self-hosted runner labels (e.g. a future gcp-prod, or a per-account
# AWS tenant label) MUST be added here so the gate cannot be bypassed.
_SELF_HOSTED_CLASS_LABELS = frozenset({"self-hosted", "gcp-dev"})


def _dw_is_self_hosted(job: dict) -> bool:
    ro = _dw_runs_on(job)
    if isinstance(ro, str):
        return ro in _SELF_HOSTED_CLASS_LABELS
    if isinstance(ro, (list, tuple)):
        return any(label in _SELF_HOSTED_CLASS_LABELS for label in ro)
    return False


def _dw_result_guarded_upstreams(if_expr) -> set:
    """Upstream job ids referenced as ``needs.<job>.result`` in an ``if:``."""
    return set(_DW_RESULT_REF.findall(_dw_normalize_expr(if_expr)))


# --- Constrained GitHub Actions `if:` expression evaluator ----------------- #
# A substring check cannot PROVE fail-closed gating: an expression that also
# ORs in `failure`/`cancelled` still contains the `success || skipped` text,
# and a correct gate written a different way would be wrongly rejected. So the
# model parses the `if:` and evaluates the denied scenarios (`failure`,
# `cancelled`, `pull_request`) over the finite result/event vocabulary, then
# asserts the job does not run. Supports only the operators these workflows
# use - `==`, `!=`, `&&`, `||`, `!`, parentheses, string literals, and the
# `always()` status function; operands are `needs.<job>.result`,
# `needs.<job>.outputs.<key>`, `inputs.<key>`, and `github.<field>`.
def _dw_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value != ""
    return bool(value)


def _dw_loose_eq(left, right) -> bool:
    # GitHub Actions `==` compares strings case-insensitively.
    if isinstance(left, str) and isinstance(right, str):
        return left.lower() == right.lower()
    return left == right


def _dw_call_function(name: str) -> bool:
    if name == "always":
        return True
    raise _DwExprError(f"unsupported function in if-expression: {name}()")


def _dw_tokenize(expr: str) -> list:
    tokens: list = []
    pos, end = 0, len(expr)
    while pos < end:
        match = _DW_EXPR_TOKEN.match(expr, pos)
        if not match or match.end() == pos:
            raise _DwExprError(f"cannot tokenize: {expr[pos : pos + 20]!r}")
        pos = match.end()
        kind = match.lastgroup
        if kind == "str":
            tokens.append(("str", match.group("str")[1:-1]))
        elif kind == "op":
            tokens.append(("op", match.group("op")))
        elif kind == "ident":
            tokens.append(("ident", match.group("ident")))
        # whitespace (no named group) is skipped
    tokens.append(("end", ""))
    return tokens


class _DwParser:
    """Recursive-descent evaluator: `!` > comparison > `&&` > `||`."""

    def __init__(self, tokens, resolve):
        self._toks = tokens
        self._i = 0
        self._resolve = resolve

    def _peek(self):
        return self._toks[self._i]

    def _advance(self):
        tok = self._toks[self._i]
        self._i += 1
        return tok

    def _expect(self, op):
        if self._advance() != ("op", op):
            raise _DwExprError(f"expected {op!r}")

    def evaluate(self):
        value = self._parse_or()
        if self._peek()[0] != "end":
            raise _DwExprError(f"trailing tokens: {self._toks[self._i :]!r}")
        return value

    def _parse_or(self):
        value = self._parse_and()
        while self._peek() == ("op", "||"):
            self._advance()
            value = _dw_truthy(value) | _dw_truthy(self._parse_and())
        return value

    def _parse_and(self):
        value = self._parse_not()
        while self._peek() == ("op", "&&"):
            self._advance()
            value = _dw_truthy(value) & _dw_truthy(self._parse_not())
        return value

    def _parse_not(self):
        if self._peek() == ("op", "!"):
            self._advance()
            return not _dw_truthy(self._parse_not())
        return self._parse_cmp()

    def _parse_cmp(self):
        left = self._parse_primary()
        token = self._peek()
        if token in (("op", "=="), ("op", "!=")):
            self._advance()
            equal = _dw_loose_eq(left, self._parse_primary())
            return equal if token == ("op", "==") else not equal
        return left

    def _parse_primary(self):
        token = self._advance()
        if token == ("op", "("):
            value = self._parse_or()
            self._expect(")")
            return value
        if token[0] == "str":
            return token[1]
        if token[0] == "ident":
            if self._peek() == ("op", "("):
                self._advance()
                self._expect(")")
                return _dw_call_function(token[1])
            return self._resolve(token[1])
        raise _DwExprError(f"unexpected token {token!r}")


def _dw_evaluate_if(
    if_expr,
    *,
    results=None,
    event_name="workflow_dispatch",
    ref="refs/heads/aws-dev",
    base_ref="",
    inputs_true=True,
) -> bool:
    """Evaluate a job ``if:`` against a permissive context; return whether the
    job would run. Unspecified upstream results default to ``success``, every
    ``needs.*.outputs.*`` to ``true``, and every ``inputs.*`` to
    ``inputs_true`` - so the only thing that flips the outcome is the scenario
    under test (a failed upstream, a pull_request event)."""
    expr = _dw_normalize_expr(if_expr)
    if not expr:
        return True  # a job with no `if:` is always eligible
    results = results or {}

    def resolve(path):
        parts = path.split(".")
        head = parts[0]
        if head == "needs" and len(parts) >= 3:
            job, field = parts[1], parts[2]
            if field == "result":
                return results.get(job, "success")
            if field == "outputs":
                return "true"
            return "success"
        if head == "inputs":
            return inputs_true
        if head == "github":
            field = parts[1] if len(parts) > 1 else ""
            return {
                "event_name": event_name,
                "ref": ref,
                "base_ref": base_ref,
            }.get(field, "")
        raise _DwExprError(f"unresolvable operand: {path}")

    return _dw_truthy(_DwParser(_dw_tokenize(expr), resolve).evaluate())


def _dw_job_denied_when_upstream(if_expr, upstream, result) -> bool:
    """True iff the job does NOT run when ``upstream`` has ``result`` (every
    other condition permissive). Proves a failed/cancelled upstream blocks the
    deploy job (#781)."""
    return not _dw_evaluate_if(if_expr, results={upstream: result})


def _dw_job_denied_on_pull_request(if_expr) -> bool:
    """True iff the job does NOT run on a ``pull_request`` event (every other
    condition permissive). Proves PR events cannot reach the job (ADR-003-R5)."""
    return not _dw_evaluate_if(if_expr, event_name="pull_request")


def _dw_job_runs_when_eligible(if_expr) -> bool:
    """Sanity: the permissive context actually runs the job, so a denied-case
    assertion is meaningful and not vacuously satisfied."""
    return _dw_evaluate_if(if_expr)


def _dw_upstream_gating_violations(wf, deploy_job_ids):
    """Return ``[(job_id, upstream, result), ...]`` for deploy jobs that still
    RUN when a result-gated upstream is ``failure`` or ``cancelled`` (fail-open,
    the #781 class). Empty list means every deploy job fails closed."""
    found = []
    for jid in deploy_job_ids:
        expr = _dw_job_if(_dw_get_job(wf, jid, "deploy.yml"))
        for upstream in sorted(_dw_result_guarded_upstreams(expr)):
            for bad in ("failure", "cancelled"):
                if not _dw_job_denied_when_upstream(expr, upstream, bad):
                    found.append((jid, upstream, bad))
    return found


# --- dorny/paths-filter change-filter coverage (#913 / R-A2) --------------- #
def _dw_parse_paths_filter(wf, job_id, step_id, name="deploy.yml") -> dict:
    """Return ``{filter_name: [patterns]}`` from a dorny/paths-filter step.

    The action's ``filters`` input is itself a YAML document (a block scalar in
    the workflow), so it is parsed a second time here."""
    import yaml

    job = _dw_get_job(wf, job_id, name)
    for step in job.get("steps", []) or []:
        if step.get("id") == step_id:
            raw = (step.get("with") or {}).get("filters")
            if not isinstance(raw, str):
                raise _DwShapeError(f"{name}:{step_id} has no string 'filters' input")
            parsed = yaml.safe_load(raw)
            if not isinstance(parsed, dict) or not parsed:
                raise _DwShapeError(f"{name}:{step_id} filters not a mapping")
            return {key: list(val) for key, val in parsed.items()}
    raise _DwShapeError(f"{name}:{job_id} has no step with id '{step_id}'")


def _dw_glob_to_regex(pattern: str) -> str:
    """Translate a micromatch-style glob to an anchored regex for the features
    the deploy filters use: ``**`` (any depth, incl. a trailing ``/`` matching
    zero or more directories), ``*`` (one path segment), and literal text."""
    i, n = 0, len(pattern)
    out = ["^"]
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern[i : i + 2] == "**":
                j = i + 2
                if pattern[j : j + 1] == "/":
                    out.append("(?:.*/)?")  # `**/` => zero or more directories
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        else:
            out.append(re.escape(char))
            i += 1
    out.append("$")
    return "".join(out)


def _dw_path_matches_any(path: str, patterns) -> bool:
    """True iff ``path`` matches any positive pattern. The deploy filters use no
    ``!`` negation and the default ``some`` quantifier, so positive-pattern
    membership is the full contract for them."""
    for pattern in patterns:
        if pattern.startswith("!"):
            continue
        if re.match(_dw_glob_to_regex(pattern), path):
            return True
    return False


# --- branch/event routing (#892) ------------------------------------------- #
def _dw_extract_set_environment_script(wf, name="deploy.yml") -> str:
    """Return the ``run`` body of the ``changes`` job's ``Set environment`` step."""
    job = _dw_get_job(wf, "changes", name)
    for step in job.get("steps", []) or []:
        if step.get("id") == "env" or step.get("name") == "Set environment":
            run = step.get("run")
            if not isinstance(run, str):
                raise _DwShapeError(f"{name}: 'Set environment' step has no run script")
            return run
    raise _DwShapeError(f"{name}: no 'Set environment' step in 'changes' job")


def _dw_evaluate_env(script, event_name, ref="", base_ref="") -> dict:
    """Execute the workflow's own ``Set environment`` bash and return its
    ``GITHUB_OUTPUT`` key/value pairs. Only literal event/branch strings reach
    bash - no secrets, no shell trace - matching GitHub's default
    ``bash -e -o pipefail`` shell."""
    import tempfile

    rendered = script.replace("${{ github.event_name }}", event_name).replace(
        "${{ github.base_ref }}", base_ref
    )
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "github_output")
        Path(out_path).touch()
        env = {
            "PATH": os.environ.get("PATH", ""),
            "GITHUB_REF": ref,
            "GITHUB_OUTPUT": out_path,
        }
        proc = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", rendered],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            raise _DwShapeError(
                f"Set environment script exited {proc.returncode}: {proc.stderr.strip()}"
            )
        outputs = {}
        for line in Path(out_path).read_text().splitlines():
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                outputs[key] = val
    return outputs


# --- ADR-003-R5 hard check: no pull_request reaches a self-hosted deploy job #
_RUNNER_EXPOSURE_CHECK = "deploy-workflow-runner-exposure"
_RUNNER_EXPOSURE_RULE = "ADR-003-R5"


def _runner_exposure_violation(path: str, message: str) -> Violation:
    return Violation(_RUNNER_EXPOSURE_CHECK, _RUNNER_EXPOSURE_RULE, path, message)


def _deploy_runner_exposure_relevant(files: list[str] | None) -> bool:
    if files is None:
        return True
    relevant = set(_DW_REUSABLE_WORKFLOW_PATHS) | {
        _DEPLOY_WORKFLOW_PATH,
        _ADR_GUARD_SCRIPT_PATH,
    }
    return any(path in relevant for path in files)


def check_deploy_runner_exposure(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """No pull_request event may reach a self-hosted deploy job (ADR-003-R5).

    Evaluates each reusable deploy workflow's self-hosted job ``if:`` for a
    pull_request event and requires it to fail closed. Semantic evaluation, not
    substring matching: a guard broadened with ``|| always()`` is still caught.
    """
    if not _deploy_runner_exposure_relevant(files):
        return []

    violations: list[Violation] = []
    for rel in _DW_REUSABLE_WORKFLOW_PATHS:
        if not (repo_root / rel).exists():
            violations.append(
                _runner_exposure_violation(
                    rel,
                    "Required reusable deploy workflow is missing; ADR-003-R5 "
                    "cannot verify self-hosted runner exposure",
                )
            )
            continue
        try:
            wf = _dw_load_workflow(repo_root, rel)
            job_map = _dw_jobs(wf, rel)
        except _DwShapeError as exc:
            violations.append(
                _runner_exposure_violation(
                    rel, f"workflow could not be parsed for ADR-003-R5: {exc}"
                )
            )
            continue
        for jid, job in job_map.items():
            if not _dw_is_self_hosted(job):
                continue
            expr = _dw_job_if(job)
            try:
                denied = _dw_job_denied_on_pull_request(expr)
            except _DwShapeError as exc:
                violations.append(
                    _runner_exposure_violation(
                        rel,
                        f"self-hosted job '{jid}' has an if-expression "
                        f"ADR-003-R5 cannot evaluate: {exc}",
                    )
                )
                continue
            if not denied:
                violations.append(
                    _runner_exposure_violation(
                        rel,
                        f"self-hosted job '{jid}' is reachable from a "
                        "pull_request event; ADR-003-R5 requires it gate on "
                        "github.event_name != 'pull_request'",
                    )
                )
    return violations


# --- ADR-037-R1 hard check: cloud-credentialed workflows pin action SHAs ----
# Every non-local `uses:` action in a cloud-credentialed workflow is an
# executable dependency that runs with cloud credentials; a mutable tag can be
# moved by a compromised or careless maintainer, so it must resolve to a full
# 40-hex commit SHA (supply-chain provenance, issue #1519). This mirrors the
# `_dw_*` workflow-as-data model rather than string-matching workflow text, and
# fails closed: a workflow that cannot be parsed cannot be classified.
_ACTION_PIN_CHECK = "workflow-action-sha-pinning"
_ACTION_PIN_RULE = "ADR-037-R1"
_ACTION_PIN_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ACTION_PIN_OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLOUD_AUTH_ACTIONS = (
    "aws-actions/configure-aws-credentials",
    "google-github-actions/auth",
)


def _action_pin_violation(path: str, message: str) -> Violation:
    return Violation(_ACTION_PIN_CHECK, _ACTION_PIN_RULE, path, message)


def _dw_iter_workflow_files(repo_root: Path) -> list[str]:
    """Repo-relative paths of every GitHub Actions workflow file, sorted."""
    wf_dir = repo_root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    return sorted(
        f".github/workflows/{p.name}"
        for p in wf_dir.iterdir()
        if p.is_file() and p.suffix in (".yml", ".yaml")
    )


def _dw_permissions_grant_id_token(perms) -> bool:
    if isinstance(perms, str):
        return perms.strip().lower() == "write-all"
    if isinstance(perms, dict):
        return str(perms.get("id-token", "")).strip().lower() == "write"
    return False


def _dw_job_steps(job: dict) -> list:
    steps = job.get("steps")
    return steps if isinstance(steps, list) else []


def _dw_step_uses(step) -> str | None:
    if isinstance(step, dict):
        uses = step.get("uses")
        if isinstance(uses, str):
            return uses.strip()
    return None


def _dw_step_uses_cloud_auth(step) -> bool:
    uses = _dw_step_uses(step)
    if uses and any(
        uses == a or uses.startswith(a + "@") for a in _CLOUD_AUTH_ACTIONS
    ):
        return True
    if isinstance(step, dict):
        with_block = step.get("with")
        if isinstance(with_block, dict) and "workload_identity_provider" in with_block:
            return True
    return False


def _dw_job_is_cloud_credentialed(job: dict) -> bool:
    if _dw_permissions_grant_id_token(job.get("permissions")):
        return True
    if _dw_is_self_hosted(job):
        return True
    return any(_dw_step_uses_cloud_auth(step) for step in _dw_job_steps(job))


def _dw_workflow_is_cloud_credentialed(wf: dict) -> bool:
    """True when a workflow requests cloud credentials in any form.

    Markers: top-level or job-level ``id-token: write`` (or ``write-all``), a
    self-hosted runner, a cloud-auth action, or a ``workload_identity_provider``
    input. Any one is sufficient; the classifier fails toward "credentialed" so
    an unpinned action is never silently exempted.
    """
    if _dw_permissions_grant_id_token(wf.get("permissions")):
        return True
    jobs = wf.get("jobs")
    if not isinstance(jobs, dict):
        return False
    return any(
        _dw_job_is_cloud_credentialed(job)
        for job in jobs.values()
        if isinstance(job, dict)
    )


def _dw_iter_uses_refs(wf: dict):
    """Yield ``(job_id, uses_ref)`` for every job- and step-level ``uses:``."""
    jobs = wf.get("jobs")
    if not isinstance(jobs, dict):
        return
    for jid, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_uses = job.get("uses")
        if isinstance(job_uses, str):
            yield jid, job_uses.strip()
        for step in _dw_job_steps(job):
            uses = _dw_step_uses(step)
            if uses:
                yield jid, uses


def _dw_uses_is_sha_pinned(ref: str) -> bool:
    parts = ref.rsplit("@", 1)
    if len(parts) != 2:
        return False
    after = parts[1]
    # Repository actions pin a 40-hex git commit SHA; container (`docker://`)
    # actions pin an OCI `sha256:<64 hex>` digest. Both are immutable.
    return bool(_ACTION_PIN_SHA40.match(after) or _ACTION_PIN_OCI_DIGEST.match(after))


def _workflow_action_pin_relevant(files: list[str] | None) -> bool:
    if files is None:
        return True
    return any(
        f.startswith(".github/workflows/") or f == _ADR_GUARD_SCRIPT_PATH
        for f in files
    )


def check_workflow_action_sha_pinning(
    repo_root: Path, files: list[str] | None
) -> list[Violation]:
    """Cloud-credentialed workflows pin every action to a full SHA (ADR-037-R1).

    Enumerates every ``.github/workflows/*.yml`` as data, classifies each as
    cloud-credentialed, and requires every non-local ``uses:`` reference in a
    credentialed workflow to be a full 40-hex commit SHA. Fails closed: a
    workflow that cannot be parsed cannot be classified, so it is reported.
    ``actions/*`` is included - GitHub-owned actions are executable dependencies
    too, as are ``docker://`` container actions, which must pin an OCI
    ``sha256:<64 hex>`` digest. Only local reusable-workflow refs (``./...``) are
    exempt.
    """
    import yaml  # local import: keeps PyYAML optional for non-workflow checks

    if not _workflow_action_pin_relevant(files):
        return []

    violations: list[Violation] = []
    for rel in _dw_iter_workflow_files(repo_root):
        try:
            wf = _dw_load_workflow(repo_root, rel)
        except (_DwShapeError, yaml.YAMLError) as exc:
            violations.append(
                _action_pin_violation(
                    rel,
                    "workflow could not be parsed for ADR-037-R1, so its "
                    f"cloud-credential status cannot be verified: {exc}",
                )
            )
            continue
        if not _dw_workflow_is_cloud_credentialed(wf):
            continue
        for jid, ref in _dw_iter_uses_refs(wf):
            # Local reusable-workflow refs (`./...`) are first-party and exempt.
            # `docker://` container actions are NOT exempt: they are remote
            # executable dependencies too, so they must pin an OCI digest.
            if ref.startswith("./"):
                continue
            if not _dw_uses_is_sha_pinned(ref):
                hint = (
                    "an OCI 'sha256:<64 hex>' digest"
                    if ref.startswith("docker://")
                    else "a full 40-hex commit SHA (keep a '# <version>' comment for Dependabot)"
                )
                violations.append(
                    _action_pin_violation(
                        rel,
                        f"job '{jid}' uses '{ref}' with a mutable ref; "
                        f"ADR-037-R1 requires {hint} in cloud-credentialed workflows",
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# ADR-004-R14: live cloud identifier hygiene.
#
# Strips reconnaissance-sensitive AWS infrastructure identifiers from tracked
# files and blocks their reintroduction. This is the low-entropy complement to
# gitleaks (which catches high-entropy secrets): account IDs, VPC/subnet IDs,
# and account- or UUID-suffixed S3 buckets are not secret, but they aid an
# attacker mapping a public-repo deployment's real infrastructure.
#
# Detection is by *pattern*, never by a denylist of real values - listing a
# real identifier here would re-commit the very thing the check removes. Real
# values that must stay committed (vendor connector templates whose account IDs
# must be exact; backend/state buckets read directly by `terraform init`) are
# retained via scoped `docs/adr/exceptions.yaml` entries (rule_id
# ADR-004-R14), applied centrally by `filter_excepted_violations`.
#
# Allowlist: a small fixed set of synthetic example account IDs. Placeholder
# and example forms (`vpc-xxxxxxxx`, `<your-account-id>`) are not matched at all
# because the real-identifier patterns require hex / 12 literal digits, which
# bracketed and `x`-filled placeholders cannot satisfy - so there is no
# universal `<...>` wildcard a real value could hide behind.
_IDENTIFIER_RULE_ID = "ADR-004-R14"
_IDENTIFIER_CHECK = "no-live-cloud-identifiers"

# 12-digit runs that are NOT reconnaissance-sensitive Shifter account IDs and
# are allowed to remain in tracked files:
#  - AWS documentation's canonical example account IDs + the all-zero
#    placeholder.
#  - Public AMI-publisher account IDs. These are well-known, documented AWS
#    accounts (Canonical, OffSec/Kali) used as `owner` filters to resolve
#    official base images; they are not Shifter infrastructure and changing
#    them would break AMI lookups.
_SYNTHETIC_ACCOUNT_IDS: frozenset[str] = frozenset(
    {
        "123456789012",  # AWS docs canonical example account
        "111122223333",  # AWS docs secondary example account
        "000000000000",  # explicit all-zero placeholder
        "099720109477",  # Canonical (Ubuntu) - public AMI publisher
        "679593333241",  # OffSec (Kali Linux) - public AMI publisher
    }
)

# Generated / binary files that may carry incidental digit runs and never
# carry hand-authored operational identifiers. Skipped wholesale.
_IDENTIFIER_SKIP_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip", ".tar",
    ".gz", ".tgz", ".bz2", ".xz", ".whl", ".woff", ".woff2", ".ttf", ".eot",
    ".mo", ".pyc", ".so", ".dylib", ".class", ".jar", ".wasm",
)
_IDENTIFIER_SKIP_BASENAMES: frozenset[str] = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Cargo.lock",
        ".terraform.lock.hcl",
    }
)
# Dependency lock files (uv.lock, requirements-*.lock, ...): autogenerated,
# carry pinned sha256 hashes whose decimal runs are not infrastructure IDs.
_IDENTIFIER_SKIP_SUFFIX_LOCK = ".lock"

# A real AWS account ID is exactly 12 decimal digits. The lookarounds suppress
# two false-positive shapes WITHOUT making `-` a universal account-ID boundary
# (which would miss reintroduction shapes like `account-<id>`, `aws-dev-<id>`,
# or a non-Shifter `bucket-<id>`):
#  - `(?<![0-9a-fA-F])` / `(?![0-9a-fA-F])`: not bordered by a hex char, so a
#    decimal run inside a longer hex hash is ignored.
#  - `(?<![0-9a-fA-F]{4}-)`: not the trailing 12-digit group of a UUID, whose
#    final group is preceded by `<4 hex>-` (e.g. `...-a716-446655440000`).
# A hyphen-prefixed account ID such as `account-<id>` is still caught because
# the chars before the digits (`ount-`) are not `<4 hex>-`.
_ACCOUNT_ID_RE = re.compile(
    r"(?<![0-9a-fA-F])(?<![0-9a-fA-F]{4}-)[0-9]{12}(?![0-9a-fA-F])"
)
# VPC / subnet IDs are `vpc-` / `subnet-` followed by 8 (legacy) or 17 (long)
# hex chars. The hex requirement means `vpc-xxxxxxxx` placeholders never match.
_VPC_ID_RE = re.compile(r"\bvpc-[0-9a-f]{8}(?:[0-9a-f]{9})?\b")
_SUBNET_ID_RE = re.compile(r"\bsubnet-[0-9a-f]{8}(?:[0-9a-f]{9})?\b")
# Account-ID-suffixed Shifter bucket (reveals the account): `shifter-...-<12d>`.
_ACCT_BUCKET_RE = re.compile(r"\bshifter-[a-z0-9-]+-[0-9]{12}\b")
# UUID-suffixed infra/state bucket: `shifter-[dev-]infra-<uuid>`. Retained for
# `terraform init` via a scoped path exception, flagged so the retention is
# explicit and auditable.
_UUID_BUCKET_RE = re.compile(
    r"\bshifter-[a-z0-9-]*infra-"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)

# Public IPv4 addresses in IaC (`.tf`/`.tfvars`/`.hcl`) are almost always an
# operator/participant allow-CIDR - i.e. someone's home/office IP, which is PII
# in a public repo. Flag any globally-routable IPv4 in IaC. Private (RFC1918),
# loopback, link-local, CGNAT, and documentation (RFC5737: 192.0.2 / 198.51.100
# / 203.0.113) ranges are `is_global == False` and are never flagged, so
# placeholders like `203.0.113.10/32` pass. A small allowlist covers well-known
# PUBLIC infrastructure constants that legitimately appear in IaC (Google /
# Cloudflare public DNS; GCP load-balancer health-check, IAP, and googleapis
# VIP ranges) and are not env-specific or sensitive. A genuinely required
# public IP is cleared with a scoped docs/adr/exceptions.yaml entry.
_IAC_IP_SUFFIXES: tuple[str, ...] = (".tf", ".tfvars", ".hcl")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PUBLIC_IP_ALLOW_NETS: tuple[ipaddress.IPv4Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "8.8.8.8/32", "8.8.4.4/32",             # Google Public DNS
        "1.1.1.1/32", "1.0.0.1/32",             # Cloudflare DNS
        "130.211.0.0/22", "35.191.0.0/16",      # GCP LB health-check ranges
        "35.235.240.0/20",                      # GCP Identity-Aware Proxy
        "199.36.153.4/30", "199.36.153.8/30",   # GCP private/restricted googleapis VIPs
    )
)


def _is_flaggable_public_ip(token: str) -> bool:
    """True for a globally-routable IPv4 that is not a well-known public infra
    constant - i.e. an operator/participant IP that should not be committed."""
    try:
        addr = ipaddress.ip_address(token)
    except ValueError:
        return False
    if not isinstance(addr, ipaddress.IPv4Address) or not addr.is_global:
        return False
    return not any(addr in net for net in _PUBLIC_IP_ALLOW_NETS)


def _scan_iac_public_ips(line: str) -> list[str]:
    """Return ["public IP address"] once when an IaC line carries a flaggable
    public IPv4 in its code (not in a `#` / `//` comment, where IPs are prose /
    policy examples), else []."""
    code = line.split("#", 1)[0].split("//", 1)[0]
    for token in _IPV4_RE.findall(code):
        if _is_flaggable_public_ip(token):
            return ["public IP address"]
    return []


def _identifier_skip(rel: str) -> bool:
    """True for paths that must not be scanned (binary / generated locks)."""
    basename = rel.rsplit("/", 1)[-1]
    if basename in _IDENTIFIER_SKIP_BASENAMES:
        return True
    if rel.endswith(_IDENTIFIER_SKIP_SUFFIX_LOCK):
        return True
    return rel.endswith(_IDENTIFIER_SKIP_SUFFIXES)


def _identifier_violation(rel: str, lineno: int, kind: str) -> Violation:
    """Build a violation that names the path, line, and identifier KIND only -
    never the live value (preflight error-surface rule)."""
    return Violation(
        check=_IDENTIFIER_CHECK,
        rule_id=_IDENTIFIER_RULE_ID,
        path=rel,
        message=(
            f"line {lineno}: live AWS {kind} in a tracked file (value redacted); "
            "move it to a deploy-time overlay/secret/env var or a placeholder, "
            "or add a scoped docs/adr/exceptions.yaml entry if it must stay"
        ),
    )


def _scan_identifier_line(line: str) -> list[str]:
    """Return the identifier KINDs found on a line. Bucket patterns are matched
    and masked first so the account-ID run they contain is not double-counted."""
    kinds: list[str] = []
    masked = line
    for rx, kind in ((_ACCT_BUCKET_RE, "account-suffixed S3 bucket name"),
                     (_UUID_BUCKET_RE, "infra/state S3 bucket name")):
        if rx.search(masked):
            kinds.append(kind)
            masked = rx.sub(lambda m: " " * len(m.group(0)), masked)
    for match in _ACCOUNT_ID_RE.finditer(masked):
        if match.group(0) not in _SYNTHETIC_ACCOUNT_IDS:
            kinds.append("account ID")
    if _VPC_ID_RE.search(masked):
        kinds.append("VPC id")
    if _SUBNET_ID_RE.search(masked):
        kinds.append("subnet id")
    return kinds


def _read_text_safe(path: Path) -> str | None:
    """Read a file as UTF-8, returning None for unreadable or binary content."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="ignore")


def _scan_identifier_file(path: Path, rel: str) -> list[Violation]:
    text = _read_text_safe(path)
    if text is None:
        return []
    is_iac = rel.endswith(_IAC_IP_SUFFIXES)
    violations: list[Violation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind in _scan_identifier_line(line):
            violations.append(_identifier_violation(rel, lineno, kind))
        if is_iac:
            for kind in _scan_iac_public_ips(line):
                violations.append(_identifier_violation(rel, lineno, kind))
    return violations


def _git_tracked_all(repo_root: Path) -> list[str] | None:
    """All tracked + non-ignored untracked repo-relative paths, or None when
    `repo_root` is not a git working tree (synthetic test mode)."""
    if not (repo_root / ".git").exists():
        return None
    cmd = [
        "git", "-C", str(repo_root), "ls-files", "-z",
        "--cached", "--others", "--exclude-standard",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.decode("utf-8", errors="replace")
    return [entry for entry in output.split("\0") if entry]


def _walk_all_files(repo_root: Path) -> list[str]:
    """Test-mode fallback: every file on disk under `repo_root`, skipping the
    git dir. Only reached when there is no usable git index."""
    candidates: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = _repo_relative(path, repo_root)
        if rel.startswith(".git/"):
            continue
        candidates.append(rel)
    return candidates


def _iter_identifier_candidates(repo_root: Path, files: list[str] | None) -> list[str]:
    if files is not None:
        return list(files)
    tracked = _git_tracked_all(repo_root)
    if tracked is None:
        return _walk_all_files(repo_root)
    return tracked


def check_no_terraform_operational_placeholders(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid operational placeholder strings in committed Terraform sources (ADR-004-R15).

    Scans tracked ``platform/terraform/**/*.tf`` files for known non-operational
    literals such as ``YOUR_EMAIL@example.com`` that must not ship in IaC. Real
    alert recipients and similar values belong in gitignored ``local.auto.tfvars``
    or deploy secrets, not hardcoded in ``.tf`` sources.
    """
    violations: list[Violation] = []
    placeholder_patterns = (
        re.compile(r"YOUR_EMAIL@example\.com", re.IGNORECASE),
        re.compile(r"subscriber_email_addresses\s*=\s*\[[^\]]*@example\.com", re.IGNORECASE),
    )
    for rel in _iter_identifier_candidates(repo_root, files):
        if not rel.startswith("platform/terraform/") or not rel.endswith(".tf"):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern in placeholder_patterns:
                if pattern.search(line):
                    violations.append(
                        Violation(
                            "no-terraform-operational-placeholders",
                            "ADR-004-R15",
                            rel,
                            f"Operational placeholder detected in Terraform source (line {lineno}). "
                            "Use a variable plus gitignored local.auto.tfvars or a deploy secret "
                            "instead of committing example.com alert recipients.",
                        )
                    )
                    break
    return violations


_GITHUB_OIDC_TF_PATH = "platform/terraform/global/iam/github-oidc.tf"


def check_github_oidc_no_admin_access(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid AdministratorAccess attachment on the GitHub Actions OIDC role (ADR-004-R15)."""
    if files is not None and _GITHUB_OIDC_TF_PATH not in files and not any(
        path.endswith("adr_guard.py") for path in files
    ):
        return []

    path = repo_root / _GITHUB_OIDC_TF_PATH
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8")
    if re.search(
        r'policy_arn\s*=\s*"arn:aws:iam::aws:policy/AdministratorAccess"',
        text,
    ):
        return [
            Violation(
                "github-oidc-no-admin-access",
                "ADR-004-R15",
                _GITHUB_OIDC_TF_PATH,
                "GitHub Actions OIDC role must not attach managed AdministratorAccess; "
                "use scoped inline or managed policies required by CI workflows.",
            )
        ]
    return []


def check_no_live_cloud_identifiers(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid live AWS infrastructure identifiers in tracked files (ADR-004-R14).

    Scans tracked files repo-wide (or the given `files`) for AWS account IDs,
    VPC/subnet IDs, and account- or UUID-suffixed Shifter S3 buckets. Detection
    is by pattern with a fixed synthetic-account allowlist; real values that
    must stay committed are cleared via scoped exceptions.yaml entries. Messages
    redact the matched value. Backstops gitleaks for low-entropy infrastructure
    identifiers it ignores.
    """
    violations: list[Violation] = []
    for rel in _iter_identifier_candidates(repo_root, files):
        if _identifier_skip(rel):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        violations.extend(_scan_identifier_file(path, rel))
    return violations


# ---------------------------------------------------------------------------
# ADR-004-R16: no hardcoded CTF flag literals in Mission Control runtime code.
#
# The Mission Control walkthrough page is a thin handoff to the CTFd platform;
# challenge answers and flag content belong to the CTF/Polaris content domain
# (the native `ctf` app or the standalone CTFd sync path), never to Mission
# Control Python or templates. This check is the regression backstop for #560:
# it fails closed on answer-shaped `FLAG{...}` literals in MC runtime surfaces.
# CTF flags are low-entropy and are not caught by gitleaks; this is the
# complementary repo-specific rule, scoped by path so intentional flag content
# in tests, docs, the `ctf` app, and Polaris scenario sources is not touched.
#
# Detection is by pattern, never by a denylist of real values, and violation
# messages redact the matched value. Format-hint placeholders (`FLAG{...}`,
# `FLAG{<16-hex>}`, `FLAG{}`) are intentionally NOT flagged: they describe the
# answer shape rather than carrying one.
_MC_FLAG_RULE_ID = "ADR-004-R16"
_MC_FLAG_CHECK = "no-mission-control-flag-literals"

# Mission Control runtime roots. The mission_control package is all runtime -
# its tests live under shifter_platform/tests/mission_control/, outside these
# roots - and the template tree covers inline <script> JavaScript.
_MC_RUNTIME_ROOTS: tuple[str, ...] = (
    "shifter/shifter_platform/mission_control/",
    "shifter/shifter_platform/templates/mission_control/",
)
# Only hand-authored runtime text is scanned.
_MC_FLAG_SCAN_SUFFIXES: tuple[str, ...] = (".py", ".html", ".js", ".txt")

# An answer-shaped flag literal: `flag{...}` (case-insensitive) whose brace body
# is captured so the placeholder predicate below can reject format-hint shapes.
_MC_FLAG_RE = re.compile(r"(?i)\bflag\{([^}\n]*)\}")


def _mc_flag_is_placeholder(inner: str) -> bool:
    """True only for the explicit format-hint placeholder shapes documented in
    ADR-004-R16: an empty body (``FLAG{}``), the ellipsis form (``FLAG{...}``),
    and a single angle-bracket template token (``FLAG{<16-hex>}``).

    The match is deliberately narrow so the guard fails closed: a body that
    merely *contains* a dot, an angle bracket, or other punctuation alongside
    real answer text (for example ``FLAG{my<answer>}`` or ``FLAG{real.answer.42}``)
    is a concrete answer, not a placeholder, and is flagged."""
    stripped = inner.strip()
    if not stripped:  # FLAG{}
        return True
    if set(stripped) == {"."}:  # ellipsis form FLAG{...}
        return True
    # One <...> template token and nothing else (FLAG{<16-hex>}). An answer
    # with any text outside the brackets does not match, so it stays flagged.
    return re.fullmatch(r"<[^<>]*>", stripped) is not None


def _is_mc_runtime_path(rel: str) -> bool:
    """True for a Mission Control runtime file the flag check should scan."""
    return (
        rel.startswith(_MC_RUNTIME_ROOTS)
        and rel.endswith(_MC_FLAG_SCAN_SUFFIXES)
        and "/__pycache__/" not in rel
    )


def _mc_flag_violation(rel: str, lineno: int) -> Violation:
    """Build a violation that names path + line only - never the flag value
    (preflight error-surface rule)."""
    return Violation(
        check=_MC_FLAG_CHECK,
        rule_id=_MC_FLAG_RULE_ID,
        path=rel,
        message=(
            f"line {lineno}: hardcoded CTF flag literal in Mission Control "
            "runtime code (value redacted); move challenge content to the "
            "CTF/CTFd content domain instead of shipping it in the app path"
        ),
    )


def _scan_mc_flag_file(path: Path, rel: str) -> list[Violation]:
    text = _read_text_safe(path)
    if text is None:
        return []
    violations: list[Violation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _MC_FLAG_RE.finditer(line):
            if not _mc_flag_is_placeholder(match.group(1)):
                violations.append(_mc_flag_violation(rel, lineno))
    return violations


def _iter_mc_flag_candidates(repo_root: Path, files: list[str] | None) -> list[str]:
    if files is not None:
        return [rel for rel in files if _is_mc_runtime_path(rel)]
    candidates: list[str] = []
    for root in _MC_RUNTIME_ROOTS:
        base = repo_root / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = _repo_relative(path, repo_root)
            if _is_mc_runtime_path(rel):
                candidates.append(rel)
    return candidates


def check_mission_control_no_flag_literals(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Forbid hardcoded CTF flag literals in Mission Control runtime code (ADR-004-R16).

    Scans the mission_control package and the mission_control template tree for
    answer-shaped ``FLAG{...}`` literals, skipping format-hint placeholders. The
    path scope intentionally excludes tests, docs, the native ``ctf`` app, and
    Polaris scenario sources, where flag content is legitimate. Detection is by
    pattern and messages redact the matched value. Backstops gitleaks for
    low-entropy CTF flags it ignores.
    """
    violations: list[Violation] = []
    for rel in _iter_mc_flag_candidates(repo_root, files):
        path = repo_root / rel
        if not path.is_file():
            continue
        violations.extend(_scan_mc_flag_file(path, rel))
    return violations


_PUBLISHED_CONTRACT_DIR = "shifter/installation/published_contract"
_PUBLISHED_CONTRACT_SNAPSHOT_RE = re.compile(r"^backend-bundle-contract\.v(\d+)\.json$")
_PUBLISHED_CONTRACT_CHECK = "published-contract-snapshots-immutable"
_PUBLISHED_CONTRACT_RULE = "ADR-011-R8"
# CI lanes that fetch base-branch history set this so the check fails CLOSED when it cannot
# verify immutability. Local/shallow runs (env unset) fail open so dev is not blocked.
_PUBLISHED_CONTRACT_ENFORCE_ENV = "ADR_GUARD_SNAPSHOT_ENFORCE"


def _published_contract_snapshot_names(repo_root: Path, ref: str) -> set[str] | None:
    """Frozen version-snapshot filenames under the published-contract dir at ``ref``.

    Returns an empty set when the directory does not exist at ``ref`` (a genuine first
    publication), and ``None`` when the tree could not be read at all (a git read failure) —
    the two cases are distinct so the caller can fail closed on the unreadable case.
    """
    listing = _git_text(repo_root, ["ls-tree", "--name-only", ref, f"{_PUBLISHED_CONTRACT_DIR}/"])
    if listing is None:
        return None
    names = {line.strip().rsplit("/", 1)[-1] for line in listing.splitlines() if line.strip()}
    return {name for name in names if _PUBLISHED_CONTRACT_SNAPSHOT_RE.match(name)}


def _published_contract_enforced() -> bool:
    return os.environ.get(_PUBLISHED_CONTRACT_ENFORCE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _published_contract_violation(path: str, message: str) -> Violation:
    return Violation(_PUBLISHED_CONTRACT_CHECK, _PUBLISHED_CONTRACT_RULE, path, message)


def _published_contract_snapshot_diff(repo_root: Path, ref: str, name: str, enforce: bool) -> list[Violation]:
    rel = f"{_PUBLISHED_CONTRACT_DIR}/{name}"
    head_path = repo_root / rel
    if not head_path.exists():
        return [
            _published_contract_violation(
                rel,
                "published contract version snapshot was deleted; published versions are immutable "
                "(append-only). Restore it and ship a new version snapshot instead of removing this one.",
            )
        ]
    base_content = _git_text(repo_root, ["show", f"{ref}:{rel}"])
    if base_content is None:
        if enforce:
            return [_published_contract_violation(rel, "cannot read the published snapshot at the base ref to verify immutability")]
        return []
    if head_path.read_text(encoding="utf-8") != base_content:
        return [
            _published_contract_violation(
                rel,
                "published contract version snapshot was modified; published versions are immutable "
                "(append-only). Bump contract_version and add a new snapshot instead of changing this one.",
            )
        ]
    return []


def check_published_contract_snapshots_immutable(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Published backend-bundle contract version snapshots are append-only (ADR-011-R8).

    Each ``backend-bundle-contract.v<N>.json`` records the frozen shape of a published
    contract version. Once published on the base branch, a snapshot must not be modified or
    deleted — a contract change ships a *new* version snapshot instead. This is what makes the
    breaking-change gate's oracle trustworthy, which the working tree alone cannot: the
    committed snapshot is compared against its content at the base-branch merge base.

    Enforcement is fail-open by default (a shallow clone without base history cannot compare,
    so local dev is not blocked) and fail-CLOSED when ``ADR_GUARD_SNAPSHOT_ENFORCE`` is set —
    the CI lane sets it and fetches base history (``fetch-depth: 0``), so an inability to
    resolve or read the base becomes an enforcement failure rather than a silent pass.
    """
    del files  # global repository invariant, not scoped to the changed-file set
    enforce = _published_contract_enforced()
    base_refs = _boundary_mock_base_reference_candidates(repo_root)
    if not base_refs:
        if enforce:
            return [
                _published_contract_violation(
                    _PUBLISHED_CONTRACT_DIR,
                    "cannot resolve a base ref to verify published-contract snapshot immutability; "
                    "the CI lane must fetch base-branch history (fetch-depth: 0)",
                )
            ]
        return []
    ref = base_refs[0]
    base_snapshots = _published_contract_snapshot_names(repo_root, ref)
    if base_snapshots is None:
        if enforce:
            return [
                _published_contract_violation(
                    _PUBLISHED_CONTRACT_DIR,
                    "cannot read the published-contract directory at the base ref to verify snapshot immutability",
                )
            ]
        return []
    if not base_snapshots:
        return []  # the directory does not exist at the base yet (genuine first publication)
    violations: list[Violation] = []
    for name in sorted(base_snapshots):
        violations.extend(_published_contract_snapshot_diff(repo_root, ref, name, enforce))
    return violations


_PARITY_INVENTORY_PATH = "docs/architecture/aces-migration-parity-inventory.yaml"
# The only path-bearing fields for this check. Extend this constant (not the
# traversal or classifier) when a future evidence field must be validated too.
_PARITY_INSPECTED_FIELDS: tuple[str, ...] = ("legacy_source", "validation_evidence")
_PARITY_CHECK = "aces-parity-inventory-path-integrity"
_PARITY_RULE_ID = "ADR-024-R4"
_PARITY_GLOB_METACHARS = ("*", "?", "[")
# A whitespace-bearing clause led by one of these tokens (or carrying a shell
# operator) is a shell command rather than prose. Both kinds are classify-only
# and never resolved; the distinction is for diagnostics and the four-kind
# classifier contract, not for gate behaviour.
_PARITY_COMMAND_TOKENS = frozenset(
    {
        "python3", "python", "cd", "aces", "uv", "bash", "sh", "pytest", "npx",
        "make", "go", "ruff", "mypy", "pre-commit", "git", "kubeconform",
        "kube-linter", "tflint", "helm", "terraform", "actionlint",
    }
)
# Shell expansion / substitution / brace characters make a path or glob
# candidate unsafe to resolve at all. Their presence is a fail-closed violation,
# never a silent skip.
_PARITY_UNSAFE_CHARS = ("~", "$", "`", "{", "}", "!", "\\")


def _parity_violation(message: str) -> Violation:
    return Violation(_PARITY_CHECK, _PARITY_RULE_ID, _PARITY_INVENTORY_PATH, message)


def _parity_clause_violation(row_id: str, field: str, clause: str, reason: str) -> Violation:
    return _parity_violation(f"row {row_id!r} field {field!r} clause {clause!r} {reason}")


def classify_parity_clause(clause: str) -> str:
    """Classify one trimmed evidence clause: ``path``, ``glob``, ``command``, or ``prose``.

    Syntax-led on purpose: existence is never consulted. A deleted ``foo/bar.py``
    stays classified ``path`` (and fails) instead of being reclassified as prose
    and evading the check. Path-looking substrings inside prose are not extracted.
    """
    if any(char.isspace() for char in clause):
        first = clause.split()[0]
        if (
            first in _PARITY_COMMAND_TOKENS
            or " && " in clause
            or " || " in clause
            or " | " in clause
            or " -" in clause
        ):
            return "command"
        return "prose"
    if any(char in clause for char in _PARITY_GLOB_METACHARS):
        return "glob"
    if "/" in clause or clause.startswith("."):
        return "path"
    return "prose"


def _parity_glob_base(clause: str) -> str:
    """Return the leading metacharacter-free directory portion of a glob pattern.

    Used to enforce repository containment *before* the pattern is enumerated, so
    a symlinked base directory that escapes the repository is rejected without
    following it. Returns ``""`` when the first path component already contains a
    glob metacharacter (the pattern is anchored at the repository root).
    """
    base_parts: list[str] = []
    for part in clause.split("/")[:-1]:
        if any(char in part for char in _PARITY_GLOB_METACHARS):
            break
        base_parts.append(part)
    return "/".join(base_parts)


def _validate_parity_path(
    repo_root: Path, row_id: str, field: str, clause: str, *, is_glob: bool
) -> list[Violation]:
    """Validate one ``path``/``glob`` clause: syntactic safety, containment, existence."""
    if clause.startswith("/") or Path(clause).is_absolute():
        return [_parity_clause_violation(row_id, field, clause, "must be repository-relative, not an absolute path")]
    if any(char in clause for char in _PARITY_UNSAFE_CHARS):
        return [_parity_clause_violation(row_id, field, clause, "contains an unsupported shell/expansion character")]
    if any(segment == ".." for segment in clause.split("/")):
        return [_parity_clause_violation(row_id, field, clause, "must not use '..' path traversal")]

    root = repo_root.resolve()

    if is_glob:
        # Enforce containment BEFORE enumeration: reject a glob whose literal base
        # directory (the leading metacharacter-free portion) resolves outside the
        # repository, so `linked/*.txt` where `linked` is an escaping symlink is
        # never followed or enumerated. Every miss - nothing matched, base
        # escaped, or all matches external - returns one indistinguishable
        # diagnostic, so the always-run check cannot become a boolean filename
        # oracle for the host filesystem. Referenced targets are never read.
        base = _parity_glob_base(clause)
        if base:
            try:
                base_resolved = (repo_root / base).resolve()
            except (OSError, RuntimeError):
                return [_parity_clause_violation(row_id, field, clause, "matches no path under the repository root")]
            if base_resolved != root and root not in base_resolved.parents:
                return [_parity_clause_violation(row_id, field, clause, "matches no path under the repository root")]
        try:
            matches = glob.glob(clause, root_dir=repo_root)
        except (OSError, ValueError):
            matches = []
        for match in matches:
            try:
                resolved = (repo_root / match).resolve()
            except (OSError, RuntimeError):
                continue
            if resolved == root or root in resolved.parents:
                return []  # at least one match resolves within the repository
        return [_parity_clause_violation(row_id, field, clause, "matches no path under the repository root")]

    candidate = repo_root / clause
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return [_parity_clause_violation(row_id, field, clause, "could not be resolved within the repository")]
    if resolved != root and root not in resolved.parents:
        # Absolute-path and traversal syntax is already rejected above, so this
        # only fires on a symlinked component escaping the repository. Fail
        # closed without reading the target.
        return [_parity_clause_violation(row_id, field, clause, "resolves outside the repository root")]
    if not candidate.exists():
        return [_parity_clause_violation(row_id, field, clause, "does not resolve to an existing path")]
    return []


def check_aces_parity_inventory_path_integrity(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Parity-inventory path evidence must resolve (ADR-024-R4).

    Global invariant over ``docs/architecture/aces-migration-parity-inventory.yaml``:
    every ``legacy_source`` / ``validation_evidence`` clause that is a repository
    path or glob must resolve to an existing path (glob: at least one match).
    Shell-command and prose clauses are classified and skipped. Runs regardless of
    the changed-file set because a referenced file can be moved or deleted without
    the inventory itself changing. Treats the YAML as untrusted static input: it
    only inspects path metadata, never reads referenced content, and never lets
    inventory text reach a shell, subprocess, or command-line argument.
    """
    del files  # global repository invariant, not scoped to the changed-file set
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return [
            _parity_violation(
                "PyYAML is required to validate the ACES parity inventory; "
                "install pyyaml in the runtime environment"
            )
        ]

    path = repo_root / _PARITY_INVENTORY_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [_parity_violation("parity inventory is missing or unreadable")]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return [_parity_violation("parity inventory is not valid YAML")]

    if not isinstance(data, dict):
        return [_parity_violation("parity inventory root must be a mapping")]
    rows = data.get("rows")
    if not isinstance(rows, list):
        return [_parity_violation("parity inventory 'rows' must be a list")]

    violations: list[Violation] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            violations.append(_parity_violation(f"row at index {index} must be a mapping"))
            continue
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            violations.append(_parity_violation(f"row at index {index} must have a non-empty string 'id'"))
            continue
        for field in _PARITY_INSPECTED_FIELDS:
            if field not in row:
                violations.append(_parity_violation(f"row {row_id!r} is missing field {field!r}"))
                continue
            value = row[field]
            if not isinstance(value, str):
                violations.append(_parity_violation(f"row {row_id!r} field {field!r} must be a string"))
                continue
            for raw_clause in value.split(";"):
                clause = raw_clause.strip()
                if not clause:
                    continue
                kind = classify_parity_clause(clause)
                if kind == "path":
                    violations.extend(_validate_parity_path(repo_root, row_id, field, clause, is_glob=False))
                elif kind == "glob":
                    violations.extend(_validate_parity_path(repo_root, row_id, field, clause, is_glob=True))
                # command / prose clauses are classified only, never resolved.
    return violations


# --------------------------------------------------------------------------- #
# Production-path quality-ownership conformance (#1530, GEN-002, ADR-004-R24)
#
# Reconciles .github/quality-path-filters.yaml (the single versioned
# quality-ownership contract) against the repository. Three invariants:
#   1. estate completeness  - every tracked path is a production owner or a
#      typed exclusion (unknown fails closed);
#   2. ownership completeness - every production PATH is covered, across the
#      union of its matching units, by a blocking lint AND security AND test
#      job (advisory / continue-on-error / missing jobs do not count); genuine
#      gaps are recorded as time-bounded docs/adr/exceptions.yaml entries;
#   3. routing reachability  - a representative change to each unit makes its
#      declared jobs (and matrix members) run in the real _quality.yml, while a
#      docs-only change does not select production jobs.
# The schema itself is parsed once by scripts/quality_ownership/contract.py -
# the same module the _quality.yml `paths` job uses - so there is no second
# implementation of the contract.
# --------------------------------------------------------------------------- #
_QUALITY_CONTRACT_REL = ".github/quality-path-filters.yaml"
_QUALITY_WORKFLOW_REL = ".github/workflows/_quality.yml"
_QUALITY_RULE = "ADR-004-R24"
_QUALITY_CHECK = "quality-path-ownership"
_QUALITY_RESPONSIBILITIES = ("lint", "security", "test")
# Evidence-only jobs: soft-fail, always-run, or advisory scanners that cannot
# by themselves own a required responsibility (per the #1530 preflight).
_QUALITY_ADVISORY_JOBS = frozenset(
    {
        "security-trivy-advisory",
        "security-osv-advisory",
        "secrets-gitleaks",
        "sonarcloud",
        "security-k8s",
    }
)


def _load_quality_module(repo_root: Path):
    """Load scripts/quality_ownership/contract.py as a module (the single
    contract implementation), without mutating sys.path."""
    import importlib.util

    path = repo_root / "scripts" / "quality_ownership" / "contract.py"
    spec = importlib.util.spec_from_file_location("_quality_ownership_contract", path)
    if spec is None or spec.loader is None:
        raise _DwShapeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the module's dataclasses (with `from __future__
    # import annotations`) can resolve their own namespace during processing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _quality_probe_path(pattern: str) -> str:
    if pattern.endswith("/**"):
        return pattern[:-3].rstrip("/") + "/__probe__"
    return pattern


def _quality_strip_if(if_expr) -> str:
    expr = _dw_normalize_expr(if_expr)
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2].strip()
    return expr


def _quality_eval_if(if_expr, outputs: dict) -> bool:
    """Evaluate a job ``if:`` against a controlled paths-output map, so routing
    is proven semantically (not by substring). ``needs.paths.outputs.<key>``
    resolves from ``outputs``; other operands are permissive; ``skip_tests`` is
    false and ``run_stack_smoke`` true so test/smoke jobs are eligible."""
    expr = _quality_strip_if(if_expr)
    if not expr:
        return True

    def resolve(pathstr):
        parts = pathstr.split(".")
        if parts[:3] == ["needs", "paths", "outputs"] and len(parts) >= 4:
            return outputs.get(parts[3], "false")
        if parts[0] == "needs":
            if len(parts) >= 3 and parts[2] == "result":
                return "success"
            return "true"
        if parts[0] == "inputs":
            field = parts[1] if len(parts) > 1 else ""
            return {
                "skip_tests": False,
                "run_full_matrix": False,
                "run_stack_smoke": True,
            }.get(field, False)
        if parts[0] == "github":
            return ""
        raise _DwExprError(f"unresolvable operand: {pathstr}")

    return _dw_truthy(_DwParser(_dw_tokenize(expr), resolve).evaluate())


def _quality_job_reachable(jobs: dict, job_id: str, outputs: dict, seen=None) -> bool:
    """A job runs iff its own ``if:`` is true AND every job it ``needs`` runs
    (transitively) - the real GitHub gating semantics, so a matrix generator or
    other upstream gate is honoured."""
    seen = seen or set()
    job = jobs.get(job_id)
    if job is None or job_id in seen:
        return job is not None
    if not _quality_eval_if(_dw_job_if(job), outputs):
        return False
    needs = job.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]
    return all(
        _quality_job_reachable(jobs, need, outputs, seen | {job_id}) for need in needs
    )


def _quality_ownership_completeness(contract, module, tracked, jobs, viol):
    violations = []

    def job_blocking(jobref):
        if jobref.job not in jobs:
            return (False, "missing")
        if jobref.job in _QUALITY_ADVISORY_JOBS:
            return (False, "advisory")
        if _dw_truthy(jobs[jobref.job].get("continue-on-error")):
            return (False, "continue-on-error")
        return (True, "")

    for unit in contract.units:
        for resp, refs in unit.responsibilities.items():
            for ref in refs:
                ok, why = job_blocking(ref)
                if not ok:
                    violations.append(
                        viol(
                            f"{_QUALITY_CONTRACT_REL}#{unit.id}:{resp}",
                            f"quality unit {unit.id!r} {resp} references {why} job "
                            f"{ref.job!r}; an advisory / continue-on-error / missing "
                            "job cannot own a responsibility",
                        )
                    )

    satisfies = {
        unit.id: {
            resp
            for resp, refs in unit.responsibilities.items()
            if any(job_blocking(ref)[0] for ref in refs)
        }
        for unit in contract.units
    }

    gaps: dict = {}
    for path in tracked:
        units_here = module.matching_units(contract, path)
        if not units_here:
            continue
        covered: set = set()
        for unit_id in units_here:
            covered |= satisfies.get(unit_id, set())
        missing = set(_QUALITY_RESPONSIBILITIES) - covered
        if missing:
            owner = module.most_specific_unit(contract, path) or units_here[0]
            for resp in missing:
                gaps.setdefault((owner, resp), path)

    for (unit_id, resp), path in sorted(gaps.items()):
        violations.append(
            viol(
                f"{_QUALITY_CONTRACT_REL}#{unit_id}:{resp}",
                f"no blocking {resp} owner for quality unit {unit_id!r} "
                f"(e.g. {path}); add a blocking {resp} job or record a time-bounded "
                "docs/adr/exceptions.yaml entry for this gap",
            )
        )
    return violations


_QUALITY_MATRIX_OUTPUT = {"mcp-lint": "mcp_lint_packages", "mcp-tests": "mcp_test_packages"}


def _quality_matrix_reachable(ref, resp, unit, outputs, jobs, viol):
    matrix = dict(ref.matrix)
    package = matrix.get("package")
    key = _QUALITY_MATRIX_OUTPUT.get(ref.job)
    if key is None:
        return []
    violations = []
    try:
        selected = json.loads(outputs.get(key, "[]"))
    except json.JSONDecodeError:
        selected = []
    if package not in selected:
        violations.append(
            viol(
                _QUALITY_WORKFLOW_REL,
                f"quality unit {unit.id!r} {resp} matrix member package={package!r} "
                f"is not selected in {key} when {unit.id!r} changes",
            )
        )
    # Verify the real job actually consumes that output as its matrix source, so
    # a job wired to the wrong JSON output (or a hard-coded matrix) is caught
    # rather than trusting the classifier value alone.
    matrix_key = next(iter(matrix), None)
    job = jobs.get(ref.job) or {}
    strategy = job.get("strategy") or {}
    matrix_spec = strategy.get("matrix") or {}
    matrix_source = str(matrix_spec.get(matrix_key, "")) if matrix_key else ""
    if "fromjson" not in matrix_source.lower() or f"needs.paths.outputs.{key}" not in matrix_source:
        violations.append(
            viol(
                _QUALITY_WORKFLOW_REL,
                f"job {ref.job!r} strategy.matrix.{matrix_key} must consume "
                f"fromJSON(needs.paths.outputs.{key}) (found {matrix_source!r}); "
                "the matrix must be driven by the declared output, not a fixed list",
            )
        )
    return violations


def _quality_output_wiring_violations(contract, module, jobs, viol):
    """Verify the real paths-job output export edges, not just the classifier's
    values: every classifier-emitted key is exported as
    ``steps.detect.outputs.<key>`` (a mis-wired key silently breaks routing),
    and no classifier-sourced output exists that the contract does not emit."""
    violations = []
    paths_job = jobs.get("paths")
    if not isinstance(paths_job, dict):
        return [viol(_QUALITY_WORKFLOW_REL, "paths job is missing from the workflow")]
    declared = paths_job.get("outputs") or {}
    emitted = set(module.compute_outputs(contract, None, run_full_matrix=True).keys())
    for key in sorted(emitted):
        if key not in declared:
            violations.append(
                viol(
                    _QUALITY_WORKFLOW_REL,
                    f"paths job does not export classifier output {key!r}",
                )
            )
        elif f"steps.detect.outputs.{key}" not in str(declared[key]):
            violations.append(
                viol(
                    _QUALITY_WORKFLOW_REL,
                    f"paths output {key!r} is not wired to steps.detect.outputs.{key} "
                    f"(found {declared[key]!r}); a mis-wired output silently breaks routing",
                )
            )
    for key, value in declared.items():
        if "steps.detect.outputs." in str(value) and key not in emitted:
            violations.append(
                viol(
                    _QUALITY_WORKFLOW_REL,
                    f"paths output {key!r} is sourced from the classifier but is not an "
                    "emitted contract output",
                )
            )
    return violations


def _quality_routing_reachability(contract, module, jobs, viol):
    violations = []
    for unit in contract.units:
        probe = _quality_probe_path(unit.paths[0])
        try:
            outputs = module.compute_outputs(contract, [probe])
        except Exception as exc:  # UnknownPathError / ContractError
            violations.append(
                viol(
                    _QUALITY_CONTRACT_REL,
                    f"cannot classify probe {probe!r} for unit {unit.id!r}: {exc}",
                )
            )
            continue
        for resp, refs in unit.responsibilities.items():
            for ref in refs:
                if ref.job not in jobs:
                    continue  # missing-job already reported by completeness
                try:
                    reachable = _quality_job_reachable(jobs, ref.job, outputs)
                except _DwShapeError as exc:
                    violations.append(
                        viol(
                            _QUALITY_WORKFLOW_REL,
                            f"quality unit {unit.id!r} {resp} job {ref.job!r} has an "
                            f"if-expression the routing model cannot evaluate: {exc}",
                        )
                    )
                    continue
                if not reachable:
                    violations.append(
                        viol(
                            _QUALITY_WORKFLOW_REL,
                            f"quality unit {unit.id!r} {resp} job {ref.job!r} does not "
                            f"run when {probe!r} changes (routing unreachable)",
                        )
                    )
                    continue
                if ref.matrix:
                    violations += _quality_matrix_reachable(
                        ref, resp, unit, outputs, jobs, viol
                    )

    docs_probe = "docs/__probe__.md"
    try:
        neg = module.compute_outputs(contract, [docs_probe])
    except Exception:
        neg = None
    if neg is not None:
        # A docs-only change must not select any declared production job.
        declared_jobs = {
            ref.job
            for unit in contract.units
            for refs in unit.responsibilities.values()
            for ref in refs
            if ref.job in jobs
        }
        for job_id in sorted(declared_jobs):
            try:
                if _quality_job_reachable(jobs, job_id, neg):
                    violations.append(
                        viol(
                            _QUALITY_WORKFLOW_REL,
                            f"production job {job_id!r} is selected by a docs-only "
                            f"change ({docs_probe!r}); an exclusion must not route "
                            "production jobs",
                        )
                    )
            except _DwShapeError:
                continue  # unevaluatable if already reported above
    return violations


def _quality_package_reconciliation(contract, repo_root, viol):
    try:
        classified = _classified_packages(repo_root)
    except Exception as exc:
        return [
            viol(
                _QUALITY_CONTRACT_REL,
                f"cannot load the #1523 package classification: {exc}",
            )
        ]
    declared: set = set()
    for unit in contract.units:
        declared |= set(unit.packages)
    violations = []
    for pkg in sorted(declared - classified):
        violations.append(
            viol(
                _QUALITY_CONTRACT_REL,
                f"quality unit references package {pkg!r} that is not in the #1523 "
                "classification (scripts/check_layer_imports/layer_imports.yaml)",
            )
        )
    for pkg in sorted(classified - declared):
        violations.append(
            viol(
                _QUALITY_CONTRACT_REL,
                f"#1523 first-party package {pkg!r} has no quality-ownership unit",
            )
        )
    return violations


def check_quality_path_ownership(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Reconcile the quality-ownership contract (whole-tree invariant)."""
    del files  # whole-tree invariant

    def viol(path: str, message: str) -> Violation:
        return Violation(_QUALITY_CHECK, _QUALITY_RULE, path, message)

    try:
        module = _load_quality_module(repo_root)
    except Exception as exc:
        return [viol(_QUALITY_CONTRACT_REL, f"cannot load quality-ownership module: {exc}")]
    try:
        contract = module.load_contract(repo_root / _QUALITY_CONTRACT_REL)
    except Exception as exc:  # ContractError / OSError
        return [viol(_QUALITY_CONTRACT_REL, f"contract invalid: {exc}")]

    tracked = _git_tracked_all(repo_root)
    if tracked is None:
        tracked = _walk_all_files(repo_root)

    violations: list[Violation] = [
        viol(_QUALITY_CONTRACT_REL, err)
        for err in module.estate_violations(contract, tracked)
    ]

    try:
        workflow = _dw_load_workflow(repo_root, _QUALITY_WORKFLOW_REL)
        jobs = _dw_jobs(workflow, _QUALITY_WORKFLOW_REL)
    except _DwShapeError as exc:
        return violations + [viol(_QUALITY_WORKFLOW_REL, str(exc))]

    violations += _quality_ownership_completeness(contract, module, tracked, jobs, viol)
    violations += _quality_output_wiring_violations(contract, module, jobs, viol)
    violations += _quality_routing_reachability(contract, module, jobs, viol)
    violations += _quality_package_reconciliation(contract, repo_root, viol)
    return violations


CHECKS = {
    "adr-registry": check_adr_registry,
    "layer-imports": check_layer_imports,
    "cross-layer-model-imports": check_cross_layer_model_imports,
    "installed-apps-classified": check_installed_apps_classified,
    "guardrail-docs": check_guardrail_docs,
    "cloud-factory-seam": check_cloud_factory_seam,
    "mcp-no-shell-exec": check_mcp_no_shell_exec,
    "k8s-deployment-security-context": check_k8s_deployment_security_context,
    "k8s-network-policy-coverage": check_k8s_network_policy_coverage,
    "no-plaintext-secrets-in-tfvars": check_no_plaintext_secrets_in_tfvars,
    "no-tracked-generated-artifacts": check_no_tracked_generated_artifacts,
    "no-populated-secret-env-files": check_no_populated_secret_env_files,
    "mcp-ops-tls-strict": check_mcp_ops_tls_strict,
    "boundary-mock-policy": check_boundary_mock_policy,
    "python-complexity-gate": check_python_complexity_gate,
    "deploy-workflow-plan-scope": check_deploy_workflow_plan_scope,
    "portal-deploy-mode-source-of-truth": check_portal_deploy_mode_source_of_truth,
    "aws-platform-renders-deploy-tfvars": check_platform_renders_deploy_tfvars,
    "deploy-verification-fail-loud": check_deploy_verification_fail_loud,
    "deploy-workflow-runner-exposure": check_deploy_runner_exposure,
    "workflow-action-sha-pinning": check_workflow_action_sha_pinning,
    "no-live-cloud-identifiers": check_no_live_cloud_identifiers,
    "no-mission-control-flag-literals": check_mission_control_no_flag_literals,
    "no-terraform-operational-placeholders": check_no_terraform_operational_placeholders,
    "github-oidc-no-admin-access": check_github_oidc_no_admin_access,
    "documentation-coverage": check_documentation_coverage,
    "published-contract-snapshots-immutable": check_published_contract_snapshots_immutable,
    "no-agent-attribution": check_no_agent_attribution,
    "aces-parity-inventory-path-integrity": check_aces_parity_inventory_path_integrity,
    "quality-path-ownership": check_quality_path_ownership,
}
CHECK_LEVELS = {
    "fast": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "installed-apps-classified",
        "guardrail-docs",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
        "no-plaintext-secrets-in-tfvars",
        "no-tracked-generated-artifacts",
        "no-populated-secret-env-files",
        "mcp-ops-tls-strict",
        "boundary-mock-policy",
        "python-complexity-gate",
        "deploy-workflow-plan-scope",
        "portal-deploy-mode-source-of-truth",
        "aws-platform-renders-deploy-tfvars",
        "deploy-verification-fail-loud",
        "deploy-workflow-runner-exposure",
        "workflow-action-sha-pinning",
        "no-live-cloud-identifiers",
        "no-mission-control-flag-literals",
        "no-terraform-operational-placeholders",
        "github-oidc-no-admin-access",
        "documentation-coverage",
        "published-contract-snapshots-immutable",
        "no-agent-attribution",
        "quality-path-ownership",
    ],
    "ci": [
        "adr-registry",
        "layer-imports",
        "cross-layer-model-imports",
        "installed-apps-classified",
        "cloud-factory-seam",
        "mcp-no-shell-exec",
        "k8s-deployment-security-context",
        "k8s-network-policy-coverage",
        "no-plaintext-secrets-in-tfvars",
        "no-tracked-generated-artifacts",
        "no-populated-secret-env-files",
        "mcp-ops-tls-strict",
        "boundary-mock-policy",
        "python-complexity-gate",
        "deploy-workflow-plan-scope",
        "portal-deploy-mode-source-of-truth",
        "aws-platform-renders-deploy-tfvars",
        "deploy-verification-fail-loud",
        "deploy-workflow-runner-exposure",
        "workflow-action-sha-pinning",
        "no-live-cloud-identifiers",
        "no-mission-control-flag-literals",
        "no-terraform-operational-placeholders",
        "github-oidc-no-admin-access",
        "documentation-coverage",
        "published-contract-snapshots-immutable",
        "no-agent-attribution",
        "aces-parity-inventory-path-integrity",
        "quality-path-ownership",
    ],
    "all": list(CHECKS),
}


def _parse_args() -> argparse.Namespace:
    valid_checks = sorted(CHECKS)
    parser = argparse.ArgumentParser(description="Run ADR conformance checks")
    parser.add_argument("--checks", nargs="*", default=[], help=f"Explicit checks to run ({', '.join(valid_checks)})")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true", help="Check the full repo")
    scope.add_argument("--changed", action="store_true", help="Check staged or modified files")
    scope.add_argument("--files", nargs="+", help="Check specific repo-relative files")
    parser.add_argument(
        "--level",
        choices=sorted(CHECK_LEVELS),
        default="fast",
        help="Named check profile",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    args = parser.parse_args()
    if args.checks:
        invalid = set(args.checks) - set(valid_checks)
        if invalid:
            parser.error(f"invalid check(s): {', '.join(sorted(invalid))} (choose from {', '.join(valid_checks)})")
    return args


def _selected_files(args: argparse.Namespace, repo_root: Path) -> list[str] | None:
    if args.all:
        return None
    if args.changed:
        return _normalize_files(get_changed_files(repo_root), repo_root)
    if args.files:
        return _normalize_files(args.files, repo_root)
    return None


def _print_text(violations: list[Violation], checks: list[str], files: list[str] | None) -> None:
    if not violations:
        scope = "all files" if files is None else f"{len(files)} file(s)"
        print(f"ADR guard passed: {', '.join(checks)} on {scope}")
        return

    print("ADR guard failed:")
    for violation in violations:
        print(f"- [{violation.rule_id}] {violation.path}: {violation.message} (check: {violation.check})")


def main() -> int:
    args = _parse_args()
    repo_root = REPO_ROOT
    files = _selected_files(args, repo_root)
    checks = args.checks or CHECK_LEVELS[args.level]
    try:
        exceptions = load_adr_exceptions(repo_root)
    except (OSError, ValueError, json.JSONDecodeError):
        exceptions = []

    violations: list[Violation] = []
    for check in checks:
        violations.extend(CHECKS[check](repo_root, files))
    violations = filter_excepted_violations(violations, exceptions)

    if args.json:
        payload = {
            "checks": checks,
            "files": files,
            "violations": [violation.__dict__ for violation in violations],
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_text(violations, checks, files)

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
