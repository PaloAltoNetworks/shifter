#!/usr/bin/env python3
"""
Hook to remind Claude about AWS log locations when investigating issues.

Triggers on: aws logs commands
Purpose: Provide context about which log groups to check for different issues
"""

import json
import sys

def main():
    # Read hook input
    input_data = json.loads(sys.stdin.read())

    # Only trigger on Bash tool
    if input_data.get("tool_name") != "Bash":
        return

    command = input_data.get("tool_input", {}).get("command", "")

    # Check if this is an AWS logs command
    if "aws logs" not in command:
        return

    # Print reminder to stderr (shown to Claude but doesn't block)
    reminder = """
┌─────────────────────────────────────────────────────────────────────────────┐
│  AWS LOGS QUICK REFERENCE                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  Portal App:     /portal/dev-portal                                         │
│  Provisioner:    /ecs/dev-portal-pulumi-provisioner                         │
│  Guacamole:      /ecs/dev-portal-guacamole-client, /ecs/dev-portal-guacd    │
│  Network FW:     /aws/network-firewall/dev-range                            │
│  RDS:            /aws/rds/instance/dev-portal-db/postgresql                 │
│                                                                             │
│  Full reference: .claude/hooks/aws_logs_guide.md                            │
└─────────────────────────────────────────────────────────────────────────────┘
"""
    print(reminder, file=sys.stderr)

if __name__ == "__main__":
    main()
