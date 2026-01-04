#!/usr/bin/env python3
"""Check all cross-layer imports between service layers.

The Shifter platform has five service layers:
  - shared
  - engine
  - cms
  - management
  - mission_control

This script shows ALL imports from each layer to every other layer,
giving a complete picture of the dependency matrix.

Usage:
    python scripts/check_layer_imports.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ALL_LAYERS = ["shared", "engine", "cms", "management", "mission_control"]

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
        except Exception:
            continue

        for match in set(IMPORT_PATTERN.findall(content)):
            # Extract the base layer from the full path (e.g., "shared" from "shared.exceptions")
            base_layer = match.split(".")[0]
            imports[base_layer].add(match)

    return imports


def main():
    """Show all cross-layer imports as JSON."""
    script_dir = Path(__file__).parent
    base_path = script_dir.parent / "shifter" / "shifter_platform"

    if not base_path.exists():
        print(json.dumps({"error": f"{base_path} not found"}), file=sys.stderr)
        return 1

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

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
