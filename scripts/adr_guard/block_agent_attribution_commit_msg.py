#!/usr/bin/env python3
"""pre-commit commit-msg hook: reject prohibited AI/agent attribution."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from agent_attribution import find_agent_attribution_matches


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <commit-msg-file>", file=sys.stderr)
        return 2

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    matches = find_agent_attribution_matches(text)
    if not matches:
        return 0

    print(
        "Commit message contains prohibited AI/agent attribution. Remove it and retry.",
        file=sys.stderr,
    )
    for match in matches:
        print(f"  - {match.rule}: {match.excerpt}", file=sys.stderr)
    print(
        "Disable Cursor commit/PR attribution in ~/.cursor/cli-config.json and .cursor/cli.json.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
