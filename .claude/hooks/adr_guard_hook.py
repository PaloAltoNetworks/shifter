#!/usr/bin/env python3
"""Run ADR guard on files edited by Claude."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_GUARD = REPO_ROOT / "scripts" / "adr_guard" / "adr_guard.py"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return 0

    path = Path(file_path)
    if not path.is_absolute():
        path = REPO_ROOT / path

    try:
        rel_path = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return 0

    result = subprocess.run(
        [
            "python3",
            str(ADR_GUARD),
            "--files",
            rel_path,
            "--checks",
            "adr-registry",
            "layer-imports",
            "cross-layer-model-imports",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return 0

    if result.stdout:
        print(result.stdout, file=sys.stderr, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return 2


if __name__ == "__main__":
    sys.exit(main())
