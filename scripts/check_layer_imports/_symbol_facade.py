#!/usr/bin/env python3
"""Per-symbol facade allowlist analysis (ADR-001-R4).

Extracted from ``check_layer_imports.py`` to keep that module under the
file-length limit and to isolate the symbol-restricted facade-seam logic: a
presentation layer may reach a symbol-restricted facade (for example
``mission_control -> engine.services``) only via ``from <facade> import
<sanctioned symbol>``; every other shape is a violation.
"""

import ast
from collections import defaultdict
from pathlib import Path

import yaml


def load_allowed_symbols(config_path: Path) -> dict[str, dict[str, list[str]]]:
    """Load per-symbol facade allowlists from the YAML config (ADR-001-R4).

    Returns dict mapping from_layer -> {facade -> [allowed symbol names]}. When a
    (from_layer, facade) pair appears here, that layer may import from the facade
    ONLY the enumerated symbols; every other public symbol, and any bare module
    import of the facade, is a violation.
    """
    with open(Path(config_path).resolve()) as f:
        config = yaml.safe_load(f)
    return config.get("allowed_symbols", {}) or {}


def _is_public_facade_descendant(module: str, facade: str) -> bool:
    """True when ``module`` is a PUBLIC descendant module of ``facade``.

    ``engine.services.runtime`` is a descendant of ``engine.services``. A private
    component anywhere in the remainder (``engine.services._x``) is not, because
    private split-package modules are already rejected by the public-facade rule
    (ADR-001-R1); this keeps the two rules from double-reporting the same import.
    """
    if not module.startswith(facade + "."):
        return False
    remainder = module[len(facade) + 1 :]
    return not any(part.startswith("_") for part in remainder.split("."))


def _collect_symbol_importfrom(
    node: ast.ImportFrom,
    restricted_facades: set[str],
    from_symbols: dict[str, set[str]],
    bypass: set[str],
) -> None:
    """Classify one ``from ... import ...`` node against the restricted facades."""
    module = node.module
    if not module:
        return
    for facade in restricted_facades:
        if node.level == 0 and module == facade:
            from_symbols[facade].update(alias.name for alias in node.names if not alias.name.startswith("_"))
        elif module == facade or _is_public_facade_descendant(module, facade):
            # Relative facade import (level > 0) or a facade descendant.
            bypass.add(module)


def _collect_symbol_import(node: ast.Import, restricted_facades: set[str], bypass: set[str]) -> None:
    """Record bare ``import <facade>`` / ``import <facade>.sub`` bypasses."""
    for alias in node.names:
        for facade in restricted_facades:
            if alias.name == facade or _is_public_facade_descendant(alias.name, facade):
                bypass.add(alias.name)


def _facade_symbol_imports_in_tree(tree: ast.AST, restricted_facades: set[str]) -> tuple[dict[str, set[str]], set[str]]:
    """Return (public symbols imported per restricted facade, non-facade bypasses).

    The only sanctioned shape for a symbol-restricted facade is an absolute
    ``from <facade> import <name>``; its public names feed the allowlist check.
    Every other shape that reaches the facade or one of its public descendants is
    a bypass (ADR-001-R4): a relative ``from ..<facade> import name``, a descendant
    ``from <facade>.sub import name``, a bare ``import <facade>``, or
    ``import <facade>.sub``. Private ``_``-prefixed targets are left to the
    public-facade rule (ADR-001-R1) so the two rules do not double-report.
    """
    from_symbols: dict[str, set[str]] = defaultdict(set)
    bypass: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            _collect_symbol_importfrom(node, restricted_facades, from_symbols, bypass)
        elif isinstance(node, ast.Import):
            _collect_symbol_import(node, restricted_facades, bypass)
    return from_symbols, bypass


def get_facade_symbol_imports(layer_path: Path, restricted_facades: set[str]) -> tuple[dict[str, set[str]], set[str]]:
    """Return per-facade imported public symbols and module-import bypasses under a layer."""
    from_symbols: dict[str, set[str]] = defaultdict(set)
    module_bypass: set[str] = set()

    if not restricted_facades or not layer_path.exists():
        return from_symbols, module_bypass

    for py_file in layer_path.rglob("*.py"):
        try:
            tree = ast.parse(py_file.resolve().read_text())
        except (OSError, SyntaxError):
            # nosec B112 - skip unreadable / unparseable files
            continue
        file_symbols, file_bypass = _facade_symbol_imports_in_tree(tree, restricted_facades)
        for facade, names in file_symbols.items():
            from_symbols[facade].update(names)
        module_bypass.update(file_bypass)

    return from_symbols, module_bypass


def compute_symbol_facade_violations(
    from_layer: str,
    from_symbols: dict[str, set[str]],
    module_bypass: set[str],
    allowed_symbols: dict[str, dict[str, list[str]]],
) -> list[str]:
    """Return disallowed symbol imports and module-import bypasses for a layer."""
    restrictions = allowed_symbols.get(from_layer, {})
    violations: list[str] = []
    for facade, names in from_symbols.items():
        allowed_names = set(restrictions.get(facade, []))
        violations.extend(f"{facade}.{name}" for name in names if name not in allowed_names)
    violations.extend(f"{module} (non-facade import)" for module in module_bypass)
    return sorted(violations)


def analyze_symbol_facade_imports(
    base_path: Path, allowed_symbols: dict[str, dict[str, list[str]]], all_layers: list[str]
) -> dict[str, list[str]]:
    """Analyze per-symbol facade allowlist violations per layer (ADR-001-R4)."""
    result: dict[str, list[str]] = {}

    for from_layer in all_layers:
        restricted = set(allowed_symbols.get(from_layer, {}))
        if not restricted:
            continue
        from_symbols, module_bypass = get_facade_symbol_imports(base_path / from_layer, restricted)
        violations = compute_symbol_facade_violations(from_layer, from_symbols, module_bypass, allowed_symbols)
        if violations:
            result[from_layer] = violations

    return result


def apply_symbol_facade_violations(stats: dict[str, object], symbol_facade: dict[str, list[str]]) -> None:
    """Roll per-symbol facade-allowlist violations into summary stats (ADR-001-R4)."""
    for from_layer, modules in symbol_facade.items():
        stats["violations"] = int(stats["violations"]) + len(modules)
        layers_with_violations = stats["layers_with_violations"]
        if from_layer not in layers_with_violations:
            layers_with_violations.append(from_layer)
        violation_details = stats["violation_details"]
        violation_details.append(
            {
                "from": from_layer,
                "to": modules[0].split(".")[0] if modules else "",
                "modules": modules,
            }
        )
