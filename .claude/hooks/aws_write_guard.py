#!/usr/bin/env python3
"""
AWS Write Guard Hook

Blocks AWS CLI write operations unless Claude has explicit user direction.
This prevents accidental infrastructure changes during debugging/exploration.

Write operations are detected by looking for common mutating subcommands:
create, update, delete, put, modify, register, deregister, start, stop,
terminate, run, force-new-deployment, etc.

Exit codes:
  0 = allow command
  2 = block command (shows error to user)
"""

import json
import re
import sys

# AWS CLI write operation patterns
# These are subcommands/flags that indicate a mutating operation
WRITE_PATTERNS = [
    # CRUD operations
    r"\bcreate[-_]",
    r"\bdelete[-_]",
    r"\bupdate[-_]",
    r"\bmodify[-_]",
    r"\bput[-_]",
    r"\bremove[-_]",
    # Lifecycle operations
    r"\bstart[-_]",
    r"\bstop[-_]",
    r"\bterminate[-_]",
    r"\breboot[-_]",
    r"\brun[-_]",
    # Registration
    r"\bregister[-_]",
    r"\bderegister[-_]",
    # ECS specific
    r"--force-new-deployment",
    # S3 write operations
    r"\bcp\b",
    r"\bmv\b",
    r"\brm\b",
    r"\bsync\b",
    # IAM/security
    r"\battach[-_]",
    r"\bdetach[-_]",
    r"\badd[-_]",
    # Tags
    r"\btag[-_]resource",
    r"\buntag[-_]resource",
    # Generic dangerous patterns
    r"\bexecute[-_]",
    r"\binvoke\b",
    r"\bsend[-_]",
]

# Safe read-only patterns (allowlist for common read operations)
SAFE_PATTERNS = [
    r"\bdescribe[-_]",
    r"\blist[-_]",
    r"\bget[-_]",
    r"\bwait\b",
    r"--query",
    r"--output",
    r"\bhelp\b",
]


def is_aws_command(command: str) -> bool:
    """Check if command is an AWS CLI command."""
    # Match 'aws ' at start or after && or ; or |
    return bool(re.search(r"(^|&&|\||;)\s*aws\s+", command))


def is_write_operation(command: str) -> bool:
    """Check if the AWS command is a write/mutating operation."""
    command_lower = command.lower()

    # Check for write patterns
    for pattern in WRITE_PATTERNS:
        if re.search(pattern, command_lower):
            return True

    return False


def is_safe_operation(command: str) -> bool:
    """Check if the command is a safe read-only operation."""
    command_lower = command.lower()

    # If it matches a safe pattern and no write patterns, it's safe
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, command_lower):
            return True

    return False


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # If we can't parse input, allow the command
        sys.exit(0)

    command = data.get("tool_input", {}).get("command", "")

    # Only check AWS commands
    if not is_aws_command(command):
        sys.exit(0)

    # Check if it's a write operation
    if is_write_operation(command):
        # Allow if user has explicitly directed this operation
        if "# user-directed" in command:
            sys.exit(0)

        # Block with guidance
        error_msg = """
┌─────────────────────────────────────────────────────────────────────────────┐
│  AWS WRITE OPERATION BLOCKED                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  This command appears to modify AWS infrastructure.                         │
│                                                                             │
│  Write operations require explicit user direction. If the user has          │
│  explicitly asked you to make this change, add a comment to the command     │
│  indicating so:                                                             │
│                                                                             │
│    aws ecs update-service ... # user-directed                               │
│                                                                             │
│  If you're exploring or debugging, use read-only commands instead:          │
│    - aws ... describe-*                                                     │
│    - aws ... list-*                                                         │
│    - aws ... get-*                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
"""
        print(error_msg, file=sys.stderr)
        sys.exit(2)

    # Allow the command
    sys.exit(0)


if __name__ == "__main__":
    main()
