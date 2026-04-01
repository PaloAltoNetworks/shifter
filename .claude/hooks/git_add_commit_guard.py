#!/usr/bin/env python3
"""
Git Add/Commit Guard Hook (PreToolUse)

Blocks git add and git commit unless the user has explicitly directed it.
Claude should never stage or commit on its own — the user signs commits.

Exit codes:
  0 = allow command
  2 = block command (shows error to user)
"""
import json
import sys

data = json.load(sys.stdin)
command = data.get("tool_input", {}).get("command", "")

blocked = [
    "git add ",
    "git add.",
    "git commit",
]

for cmd in blocked:
    if cmd in command:
        print(
            f"BLOCKED: Claude may not run '{cmd}'. The user handles all git add/commit operations.",
            file=sys.stderr,
        )
        sys.exit(2)

sys.exit(0)
