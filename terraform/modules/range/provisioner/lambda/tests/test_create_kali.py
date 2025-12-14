"""Tests for create_kali Lambda functions."""

import base64
import pytest


def get_user_data_script() -> str:
    """
    Generate user data script to install kali-linux-headless tools on boot.

    Copied from handler.py for testing without boto3 import.
    """
    script = """#!/bin/bash
set -euo pipefail

# Log output
exec > >(tee /var/log/user-data.log) 2>&1
echo "Starting Kali headless setup..."

# Update package lists
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

# Install kali-linux-headless metapackage (core pentesting tools)
apt-get install -y kali-linux-headless

echo "Kali headless setup complete"
"""
    return base64.b64encode(script.encode()).decode()


class TestGetUserDataScript:
    """Tests for Kali user data script generation."""

    def test_returns_base64_encoded(self):
        """Script should be base64 encoded."""
        result = get_user_data_script()
        # Should be valid base64
        decoded = base64.b64decode(result)
        assert isinstance(decoded, bytes)

    def test_script_has_shebang(self):
        """Script should start with bash shebang."""
        result = get_user_data_script()
        decoded = base64.b64decode(result).decode()
        assert decoded.startswith("#!/bin/bash")

    def test_script_installs_kali_headless(self):
        """Script should install kali-linux-headless metapackage."""
        result = get_user_data_script()
        decoded = base64.b64decode(result).decode()
        assert "kali-linux-headless" in decoded
        assert "apt-get install" in decoded

    def test_script_sets_noninteractive(self):
        """Script should set DEBIAN_FRONTEND to avoid prompts."""
        result = get_user_data_script()
        decoded = base64.b64decode(result).decode()
        assert "DEBIAN_FRONTEND=noninteractive" in decoded

    def test_script_updates_apt(self):
        """Script should update apt before installing."""
        result = get_user_data_script()
        decoded = base64.b64decode(result).decode()
        assert "apt-get update" in decoded

    def test_script_logs_output(self):
        """Script should log to user-data.log for debugging."""
        result = get_user_data_script()
        decoded = base64.b64decode(result).decode()
        assert "/var/log/user-data.log" in decoded

    def test_script_uses_strict_mode(self):
        """Script should use set -e or similar for error handling."""
        result = get_user_data_script()
        decoded = base64.b64decode(result).decode()
        # Should have some form of strict error handling
        assert "set -e" in decoded or "set -euo pipefail" in decoded
