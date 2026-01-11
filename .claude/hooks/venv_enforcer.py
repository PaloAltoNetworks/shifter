#!/usr/bin/env python3
# ~/.claude/hooks/venv_enforcer.py
import json
import sys

data = json.load(sys.stdin)
command = data.get("tool_input", {}).get("command", "")

# Check if running Python/pytest without venv activation
python_commands = ["python", "pytest", "pip", "python3"]
if any(cmd in command for cmd in python_commands):
    # Check if venv is already activated in command
    if not any(
        marker in command
        for marker in ["source ", "activate", ".venv/bin/", "venv/bin/"]
    ):
        error_msg = """ERROR: Running Python command without activating venv.

REQUIRED: Find and activate the appropriate venv first.
- Search for .venv, venv, or .virtualenv directories
- Activate before running Python/pytest/pip commands
- Use: source <venv-path>/bin/activate && <your-command>
"""
        print(error_msg, file=sys.stderr)
        sys.exit(2)

sys.exit(0)
