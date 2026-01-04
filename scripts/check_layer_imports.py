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
