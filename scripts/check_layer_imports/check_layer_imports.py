#!/usr/bin/env python3
"""Check all cross-layer imports between service layers.

The Shifter platform has five service layers:
  - shared        (common schemas, enums, exceptions)
  - engine        (infrastructure provisioning)
  - cms           (content management)
  - management    (admin/platform management)
  - mission_control (presentation/UI layer)

This script validates imports against explicit rules defined in layer_imports.yaml.
Any import not in the allowed list is a violation.

Usage:
    python scripts/check_layer_imports/check_layer_imports.py
    python scripts/check_layer_imports/check_layer_imports.py -o report.json
"""

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ALL_LAYERS = ["shared", "engine", "cms", "management", "mission_control", "ctf"]

# Regex to match imports from our layers (including indented imports in functions)
# Captures the full module path (e.g., "shared.exceptions" from "from shared.exceptions import X")
IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+((?:shared|engine|cms|management|mission_control|ctf)(?:\.\w+)*)",
    re.MULTILINE,
)

# Direct cyberscript imports — only the shared layer may import cyberscript.
CYBERSCRIPT_IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+(cyberscript(?:\.\w+)*)",
    re.MULTILINE,
)

CYBERSCRIPT_ALLOWED_LAYER = "shared"


def load_allowed_imports(config_path: Path) -> dict[str, list[str]]:
    """Load allowed imports from YAML config file.

    Returns dict mapping from_layer -> list of allowed import prefixes.
    """
    # Normalize the path (collapsing any `..`) before opening so the file read is
    # the resolved target. The config path is repo-internal, but resolving keeps the
    # filesystem access explicit and traversal-free.
    with open(Path(config_path).resolve()) as f:
        config = yaml.safe_load(f)
    return config.get("allowed", {})


def is_import_allowed(from_layer: str, module_path: str, allowed: dict[str, list[str]]) -> bool:
    """Check if a specific import is allowed by the config.

    Rules:
      - ``"shared"`` is the contracts layer — allows any submodule
        (``shared.enums``, ``shared.schemas.range``, etc.).
      - For all other layers, only ``layer.services`` is a valid
        import target.  A rule like ``"cms.services"`` allows
        ``cms.services`` and ``cms.services.foo``.
      - A bare layer name like ``"engine"`` without ``.services``
        is not valid for non-shared layers (will not match anything
        useful since ``import engine`` alone is rare).

    Args:
        from_layer: The layer doing the import
        module_path: Full module path being imported (e.g., "management.services")
        allowed: Dict of allowed imports per layer

    Returns:
        True if this import is explicitly allowed, False otherwise
    """
    allowed_entries = allowed.get(from_layer, [])
    return any(_entry_allows_import(entry, module_path) for entry in allowed_entries)


def _dotted_facade_allows(entry: str, module_path: str) -> bool:
    """Return True if a dotted facade ``entry`` permits ``module_path``.

    Allow the exact facade and its PUBLIC submodules, but reject any path whose
    remainder names a private split-package module (a component that starts with
    "_", e.g. "cms.services._range_pause"). The facade is the cross-layer seam;
    private submodules are not (ADR-001-R1).
    """
    if module_path == entry:
        return True
    if not module_path.startswith(entry + "."):
        return False
    remainder = module_path[len(entry) + 1 :]
    return not any(part.startswith("_") for part in remainder.split("."))


def _entry_allows_import(entry: str, module_path: str) -> bool:
    """Return True if a single allow-list ``entry`` permits importing ``module_path``."""
    if entry == "shared":
        # shared is the contracts layer — any submodule is allowed
        return module_path == "shared" or module_path.startswith("shared.")
    if "." in entry:
        return _dotted_facade_allows(entry, module_path)
    # Bare layer name — exact match only
    return module_path == entry


def get_imports(layer_path: Path) -> dict[str, set[str]]:
    """Get all imports from a layer, grouped by target layer.

    Returns dict mapping target_layer -> set of imported module paths.
    """
    imports: dict[str, set[str]] = defaultdict(set)

    if not layer_path.exists():
        return imports

    for py_file in layer_path.rglob("*.py"):
        try:
            content = py_file.resolve().read_text()
        except Exception:
            # nosec B112 - skip unreadable files
            continue

        for match in set(IMPORT_PATTERN.findall(content)):
            # Extract the base layer from the full path (e.g., "shared" from "shared.exceptions")
            base_layer = match.split(".")[0]
            imports[base_layer].add(match)

    return imports


def get_cyberscript_imports(layer_path: Path) -> set[str]:
    """Return cyberscript module paths imported under a layer directory."""
    imports: set[str] = set()

    if not layer_path.exists():
        return imports

    for py_file in layer_path.rglob("*.py"):
        try:
            content = py_file.resolve().read_text()
        except Exception:
            # nosec B112 - skip unreadable files
            continue

        imports.update(CYBERSCRIPT_IMPORT_PATTERN.findall(content))

    return imports


def compute_cyberscript_violations(from_layer: str, modules: set[str]) -> list[str]:
    """Return cyberscript imports that violate the shared-only rule."""
    if from_layer == CYBERSCRIPT_ALLOWED_LAYER or not modules:
        return []
    return sorted(modules)


def analyze_cyberscript_imports(base_path: Path) -> dict[str, list[str]]:
    """Analyze direct cyberscript imports per layer."""
    result: dict[str, list[str]] = {}

    for from_layer in ALL_LAYERS:
        modules = get_cyberscript_imports(base_path / from_layer)
        violations = compute_cyberscript_violations(from_layer, modules)
        if violations:
            result[from_layer] = violations

    return result


def _private_facade_imports_in_tree(tree: ast.AST) -> set[str]:
    """Return ``layer.path._private`` targets from one parsed module AST."""
    targets: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
            continue
        if node.module.split(".")[0] not in ALL_LAYERS:
            continue
        targets.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name.startswith("_"))
    return targets


def get_private_facade_imports(layer_path: Path) -> set[str]:
    """Return ``layer.path._private`` targets imported via ``from ... import``.

    The regex import scan only captures the module path, so
    ``from cms.services import _range_pause`` is indistinguishable from a
    legitimate ``cms.services`` facade import. This AST pass recovers the
    imported name and, when it is private (starts with ``_``) and the module
    belongs to one of our layers, reconstructs the effective dotted target
    (``cms.services._range_pause``). Relative imports (``from ._x import y``)
    and public names are ignored.
    """
    imports: set[str] = set()

    if not layer_path.exists():
        return imports

    for py_file in layer_path.rglob("*.py"):
        try:
            tree = ast.parse(py_file.resolve().read_text())
        except (OSError, SyntaxError):
            # nosec B112 - skip unreadable / unparseable files
            continue

        imports.update(_private_facade_imports_in_tree(tree))

    return imports


def compute_private_facade_violations(from_layer: str, modules: set[str], allowed: dict[str, list[str]]) -> list[str]:
    """Return private-name facade imports that violate the public-facade rule."""
    return sorted(m for m in modules if m.split(".")[0] != from_layer and not is_import_allowed(from_layer, m, allowed))


def analyze_private_facade_imports(base_path: Path, allowed: dict[str, list[str]]) -> dict[str, list[str]]:
    """Analyze cross-layer private-name facade imports per layer."""
    result: dict[str, list[str]] = {}

    for from_layer in ALL_LAYERS:
        modules = get_private_facade_imports(base_path / from_layer)
        violations = compute_private_facade_violations(from_layer, modules, allowed)
        if violations:
            result[from_layer] = violations

    return result


def analyze_imports(base_path: Path) -> dict:
    """Analyze all cross-layer imports and return structured result."""
    result = {}

    for from_layer in ALL_LAYERS:
        layer_path = base_path / from_layer
        imports = get_imports(layer_path)

        layer_imports = {}
        for to_layer in ALL_LAYERS:
            if to_layer == from_layer:
                continue

            modules = imports.get(to_layer, set())
            if modules:
                layer_imports[to_layer] = sorted(modules)

        result[from_layer] = layer_imports

    return result


def _apply_cyberscript_violations(stats: dict[str, object], cyberscript: dict[str, list[str]]) -> None:
    """Roll cyberscript boundary violations into summary stats."""
    for from_layer, modules in cyberscript.items():
        stats["violations"] = int(stats["violations"]) + len(modules)
        layers_with_violations = stats["layers_with_violations"]
        if from_layer not in layers_with_violations:
            layers_with_violations.append(from_layer)
        violation_details = stats["violation_details"]
        violation_details.append(
            {
                "from": from_layer,
                "to": "cyberscript",
                "modules": modules,
            }
        )


def _apply_private_facade_violations(stats: dict[str, object], private_facade: dict[str, list[str]]) -> None:
    """Roll private-name facade-import violations into summary stats."""
    for from_layer, modules in private_facade.items():
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


def compute_stats(
    imports: dict[str, dict[str, list[str]]],
    allowed: dict[str, list[str]],
    cyberscript: dict[str, list[str]] | None = None,
    private_facade: dict[str, list[str]] | None = None,
) -> dict[str, object]:
    """Compute summary statistics from import analysis."""
    stats = {
        "total_cross_layer_imports": 0,
        "violations": 0,
        "clean_layers": [],
        "layers_with_violations": [],
        "violation_details": [],
    }

    for from_layer, targets in imports.items():
        layer_has_violation = False

        for to_layer, modules in targets.items():
            stats["total_cross_layer_imports"] += len(modules)

            # Find modules that are NOT in the allowed list
            violation_modules = [m for m in modules if not is_import_allowed(from_layer, m, allowed)]
            if violation_modules:
                stats["violations"] += len(violation_modules)
                layer_has_violation = True
                stats["violation_details"].append(
                    {
                        "from": from_layer,
                        "to": to_layer,
                        "modules": violation_modules,
                    }
                )

        if layer_has_violation:
            stats["layers_with_violations"].append(from_layer)

    if cyberscript:
        _apply_cyberscript_violations(stats, cyberscript)

    if private_facade:
        _apply_private_facade_violations(stats, private_facade)

    # Determine clean layers (no violations)
    for layer in ALL_LAYERS:
        has_violation = any(v["from"] == layer for v in stats["violation_details"])
        if not has_violation:
            stats["clean_layers"].append(layer)

    return stats


def print_summary(stats: dict, file=sys.stderr) -> None:
    """Print human-readable summary."""
    print("\n" + "=" * 50, file=file)
    print("LAYER IMPORT SUMMARY", file=file)
    print("=" * 50, file=file)

    print(f"\nTotal cross-layer imports: {stats['total_cross_layer_imports']}", file=file)
    print(f"Violations: {stats['violations']}", file=file)

    print(f"\nClean layers: {', '.join(stats['clean_layers']) or 'none'}", file=file)

    if stats["violation_details"]:
        print("\nViolations detected:", file=file)
        for v in stats["violation_details"]:
            print(f"  {v['from']} -> {v['to']}: {v['modules']}", file=file)
    else:
        print("\nNo violations detected!", file=file)

    print("=" * 50 + "\n", file=file)


def main():
    """Check cross-layer imports and output JSON with summary stats."""
    parser = argparse.ArgumentParser(description="Check cross-layer imports between service layers")
    parser.add_argument("-o", "--output", metavar="FILE", help="Save JSON output to file instead of stdout")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress summary output (JSON only)")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    config_path = script_dir / "layer_imports.yaml"

    if not config_path.exists():
        print(json.dumps({"error": f"Config not found: {config_path}"}), file=sys.stderr)
        return 1

    # Load allowed imports from config
    allowed = load_allowed_imports(config_path)

    # Go up two levels: check_layer_imports -> scripts -> repo root
    base_path = script_dir.parent.parent / "shifter" / "shifter_platform"

    if not base_path.exists():
        print(json.dumps({"error": f"{base_path} not found"}), file=sys.stderr)
        return 1

    # Analyze imports
    imports = analyze_imports(base_path)
    cyberscript = analyze_cyberscript_imports(base_path)
    private_facade = analyze_private_facade_imports(base_path, allowed)
    stats = compute_stats(imports, allowed, cyberscript, private_facade)

    # Build output
    output = {
        "imports": imports,
        "cyberscript_imports": cyberscript,
        "private_facade_imports": private_facade,
        "stats": stats,
    }

    json_output = json.dumps(output, indent=2)

    # Output JSON
    if args.output:
        Path(args.output).write_text(json_output)
        print(f"Output saved to {args.output}", file=sys.stderr)
        # Print summary to stderr when saving to file
        if not args.quiet:
            print_summary(stats, file=sys.stderr)
    else:
        # Print JSON then summary to stdout for easy reading
        print(json_output)
        if not args.quiet:
            print_summary(stats, file=sys.stdout)

    # Exit with error code if violations exist
    return 1 if stats["violations"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
