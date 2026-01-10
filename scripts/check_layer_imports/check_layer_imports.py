#!/usr/bin/env python3
"""Check all cross-layer imports between service layers.

The Shifter platform has five service layers:
  - shared        (lowest - common schemas, enums, exceptions)
  - engine        (infrastructure provisioning)
  - cms           (content management, orchestrates engine)
  - management    (admin/platform management)
  - mission_control (highest - presentation/UI layer)

This script shows ALL imports from each layer to every other layer,
giving a complete picture of the dependency matrix.

## Layer Dependency Rules

Valid directions (higher layers may import from lower):
  - All layers may import from: shared
  - cms, management, mission_control may import from: engine (public API only)
  - mission_control may import from: cms, management

Violations (lower layers should NOT import from higher):
  - shared should NOT import from any other layer
  - engine should NOT import from cms, management, mission_control
  - cms should NOT import from management, mission_control

## Interpreting Output

The output format is:
  "from_layer": {
    "to_layer": ["module.path", "module.submodule", ...]
  }

Example:
  "cms": {
    "engine": ["engine"]           # OK: cms calls engine's public API
    "shared": ["shared.schemas"]   # OK: cms uses shared types
  }

  "engine": {
    "cms.models": ["cms.models"]   # VIOLATION: engine reaching into cms internals
  }

## What to look for

- Imports like "layer" (e.g., "engine") = public API, usually OK
- Imports like "layer.models" = internal access, often a violation
- Imports like "layer.submodule.internal" = deep coupling, red flag

Usage:
    python scripts/check_layer_imports/check_layer_imports.py
    python scripts/check_layer_imports/check_layer_imports.py -o report.json
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ALL_LAYERS = ["shared", "engine", "cms", "management", "mission_control"]

# Layer hierarchy index (lower = lower in stack)
LAYER_INDEX = {layer: i for i, layer in enumerate(ALL_LAYERS)}

# Regex to match imports from our layers (including indented imports in functions)
# Captures the full module path (e.g., "shared.exceptions" from "from shared.exceptions import X")
IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+((?:shared|engine|cms|management|mission_control)(?:\.\w+)*)",
    re.MULTILINE,
)


def get_imports(layer_path: Path) -> dict[str, set[str]]:
    """Get all imports from a layer, grouped by target layer.

    Returns dict mapping target_layer -> set of imported module paths.
    """
    imports: dict[str, set[str]] = defaultdict(set)

    if not layer_path.exists():
        return imports

    for py_file in layer_path.rglob("*.py"):
        try:
            content = py_file.read_text()
        except Exception:  # nosec B112 - skip unreadable files
            continue

        for match in set(IMPORT_PATTERN.findall(content)):
            # Extract the base layer from the full path (e.g., "shared" from "shared.exceptions")
            base_layer = match.split(".")[0]
            imports[base_layer].add(match)

    return imports


def is_violation(from_layer: str, to_layer: str) -> bool:
    """Check if importing to_layer from from_layer is a violation.

    Violations occur when a lower layer imports from a higher layer.
    """
    return LAYER_INDEX[from_layer] < LAYER_INDEX[to_layer]


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


def compute_stats(imports: dict) -> dict:
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

            if is_violation(from_layer, to_layer):
                stats["violations"] += len(modules)
                layer_has_violation = True
                stats["violation_details"].append(
                    {
                        "from": from_layer,
                        "to": to_layer,
                        "modules": modules,
                    }
                )

        if layer_has_violation:
            stats["layers_with_violations"].append(from_layer)
        elif not targets:
            # Only mark as clean if no outbound imports at all or all are valid
            pass

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
    # Go up two levels: check_layer_imports -> scripts -> repo root
    base_path = script_dir.parent.parent / "shifter" / "shifter_platform"

    if not base_path.exists():
        print(json.dumps({"error": f"{base_path} not found"}), file=sys.stderr)
        return 1

    # Analyze imports
    imports = analyze_imports(base_path)
    stats = compute_stats(imports)

    # Build output
    output = {
        "imports": imports,
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
