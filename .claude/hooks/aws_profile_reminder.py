#!/usr/bin/env python3
"""
AWS/Terraform Profile Reminder Hook

Checks AWS CLI and Terraform commands for profile specification.
If no profile is specified, prints a reminder about available env vars.

This is a soft reminder (exit 0), not a blocker.

Exit codes:
  0 = allow command (always)
"""

import json
import re
import sys


def is_aws_command(command: str) -> bool:
    """Check if command is an AWS CLI command."""
    return bool(re.search(r"(^|&&|\||;)\s*aws\s+", command))


def is_terraform_command(command: str) -> bool:
    """Check if command is a Terraform command."""
    return bool(re.search(r"(^|&&|\||;)\s*terraform\s+", command))


def has_aws_profile(command: str) -> bool:
    """Check if AWS profile is specified via flag or env var prefix."""
    # Check for --profile flag
    if re.search(r"--profile\s+\S+", command):
        return True
    # Check for AWS_PROFILE= env var prefix
    if re.search(r"AWS_PROFILE=\S+", command):
        return True
    return False


def has_terraform_profile(command: str) -> bool:
    """Check if Terraform has AWS profile configured."""
    # Terraform uses AWS_PROFILE env var or TF_VAR for provider config
    if re.search(r"AWS_PROFILE=\S+", command):
        return True
    if re.search(r"TF_VAR_aws_profile=\S+", command):
        return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    command = data.get("tool_input", {}).get("command", "")

    needs_reminder = False

    if is_aws_command(command) and not has_aws_profile(command):
        needs_reminder = True

    if is_terraform_command(command) and not has_terraform_profile(command):
        needs_reminder = True

    if needs_reminder:
        reminder = """
+-----------------------------------------------------------------------------+
|  AWS PROFILE REMINDER                                                       |
+-----------------------------------------------------------------------------+
|  No AWS profile specified in this command.                                  |
|                                                                             |
|  Available environment variables for AWS access:                            |
|    - SHIFTER_DEV_PROFILE  : Development account profile                     |
|    - SHIFTER_PROD_PROFILE : Production account profile                      |
|    - AWS_REGION           : Default region (us-east-2)                      |
|                                                                             |
|  Usage examples:                                                            |
|    AWS_PROFILE=$SHIFTER_DEV_PROFILE aws s3 ls                               |
|    aws --profile $SHIFTER_DEV_PROFILE ec2 describe-instances                |
|                                                                             |
|  Check .env file for actual profile names.                                  |
+-----------------------------------------------------------------------------+
"""
        print(reminder, file=sys.stderr)

    # Always allow - this is just a reminder
    sys.exit(0)


if __name__ == "__main__":
    main()
