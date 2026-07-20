"""Tests for per-account ACES public-key installation (#1560)."""

import pytest

from plans.set_authorized_key import SetAuthorizedKeyPlan


class TestLinux:
    def test_installs_account_specific_key_with_strict_ownership_and_mode(self):
        plan = SetAuthorizedKeyPlan(platform="linux")
        step = plan.steps[0]

        assert "getent passwd" in step.script
        assert "authorized_keys" in step.script
        assert "chmod 700" in step.script
        assert "chmod 600" in step.script
        assert "chown" in step.script
        assert "{{ account_public_key }}" in step.script
        assert "administrators_authorized_keys" not in step.script

    def test_verifies_exact_key_without_printing_it(self):
        script = SetAuthorizedKeyPlan(platform="linux").verify_step.script

        assert "grep -Fqx" in script
        assert "authorized key installed" in script


class TestWindows:
    def test_uses_account_specific_key_path_and_acl(self):
        script = SetAuthorizedKeyPlan(platform="windows").steps[0].script

        assert "C:\\Users\\$Username\\.ssh\\authorized_keys" in script
        assert "Match User" in script
        assert "AuthorizedKeysFile" in script
        assert "Set-Acl" in script
        assert "administrators_authorized_keys" not in script
        assert "Restart-Service -Name sshd" in script
        assert "FileSecurity" in script
        assert "DirectorySecurity" in script
        assert "SetAccessRuleProtection($true, $false)" in script

    def test_validates_config_before_atomic_replacement(self):
        script = SetAuthorizedKeyPlan(platform="windows").steps[0].script

        assert "$TempConfigPath" in script
        assert "-t -f $TempConfigPath" in script
        assert "Move-Item -Force -Path $TempConfigPath -Destination $ConfigPath" in script
        assert "$LASTEXITCODE" in script

    def test_verifies_account_specific_sshd_resolution(self):
        script = SetAuthorizedKeyPlan(platform="windows").verify_step.script

        assert "sshd.exe" in script
        assert "-T" in script
        assert "authorizedkeysfile" in script.lower()
        assert "Get-Content" in script
        assert "AreAccessRulesProtected" in script
        assert "S-1-5-18" in script
        assert "S-1-5-32-544" in script
        assert "unexpected access rule" in script


def test_context_requires_username_and_public_key():
    plan = SetAuthorizedKeyPlan(platform="linux")

    with pytest.raises(ValueError, match="account_username"):
        plan.get_context({"account_public_key": "ssh-rsa AAAA"})
    with pytest.raises(ValueError, match="account_public_key"):
        plan.get_context({"account_username": "alice"})


@pytest.mark.parametrize("platform", ["linux", "windows"])
def test_context_uses_platform_quoted_username(platform: str):
    context = SetAuthorizedKeyPlan(platform=platform).get_context(
        {"account_username": "alice", "account_public_key": "ssh-rsa AAAA"}
    )

    assert "account_username" not in context
    assert context["account_username_quoted"] == ("alice" if platform == "linux" else "'alice'")


def test_rejects_unknown_platform():
    with pytest.raises(ValueError, match="Unknown platform"):
        SetAuthorizedKeyPlan(platform="solaris")
