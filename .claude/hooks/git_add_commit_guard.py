#!/usr/bin/env python3
# ~/.claude/hooks/git_add_commit_guard.py
"""
Git Add and Commit Guard Hook

Blocks git add and commit operations by Claude.

Exit codes:
  0 = allow command
  2 = block command (shows error to user)
"""
import json
import sys

data = json.load(sys.stdin)
command = data.get("tool_input", {}).get("command", "")

# Check if running Python/pytest without venv activation
python_commands = [" git add ", " git commit "]
if any(cmd in command for cmd in python_commands):
    error_msg = """ERROR: Claude may not add or commit files in git. Please ask the user to do it.
"""
    print(error_msg, file=sys.stderr)
    sys.exit(2)
sys.exit(0)
