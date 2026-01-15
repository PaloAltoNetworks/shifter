#!/usr/bin/env python3
# ~/.claude/hooks/venv_enforcer.py
import json
import sys

data = json.load(sys.stdin)
command = data.get("tool_input", {}).get("command", "")

error_msg = """Do what the user told you to do. Do not do other
things without asking first. Do not jump ahead. Do not ignore the
user's instructions. If you are unsure, disagree, or it may be unwise,
say so and ask the user to clarify.

For example. If the user says "Please investigate x", you should investigate
x and report back. Do not also do anything about x unless you were told to.
"""
print(error_msg, file=sys.stderr)
sys.exit(0)
