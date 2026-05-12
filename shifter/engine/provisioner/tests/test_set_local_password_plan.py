"""Tests for SetLocalPasswordPlan (#762)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSetLocalPasswordPlan:
    """The plan that pushes per-instance guest credentials post-boot."""

    def test_linux_step_pipes_password_through_here_doc_not_argv(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="linux")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        # Password is delivered through a chpasswd here-doc inside the
        # script body, not via stdin_input (SSMExecutor ignores stdin)
        # and not via argv. The orchestrator masks the value in log
        # capture via the ``rdp_password`` context-key heuristic.
        assert "chpasswd" in step.script
        # The user:password line MUST flow through a here-doc, not
        # through ``echo "$USER:$PASSWORD" | chpasswd`` (that shape
        # would put the value on echo's argv on some shells).
        assert "<<" in step.script
        assert "{{ rdp_username }}" in step.script
        assert "{{ rdp_password }}" in step.script

    def test_windows_step_uses_securestring_not_net_user(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="windows")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        # No argv-exposing 'net user' invocation; use Set-LocalUser with
        # ConvertTo-SecureString so the password never appears in the
        # net.exe process command line on the target.
        assert "net user" not in step.script
        assert "Set-LocalUser" in step.script
        assert "ConvertTo-SecureString" in step.script

    def test_linux_verify_step_checks_user_password_status(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="linux")
        assert plan.verify_step is not None
        assert plan.verify_step.is_verification is True
        assert "passwd -S" in plan.verify_step.script

    def test_windows_verify_step_checks_local_user_enabled(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="windows")
        assert plan.verify_step is not None
        assert plan.verify_step.is_verification is True
        assert "Get-LocalUser" in plan.verify_step.script

    def test_get_context_requires_rdp_username_and_password(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="linux")
        with pytest.raises(ValueError, match="rdp_username"):
            plan.get_context({"rdp_password": "x"})
        with pytest.raises(ValueError, match="rdp_password"):
            plan.get_context({"rdp_username": "ubuntu"})

    def test_get_context_returns_context_unchanged_on_success(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="linux")
        ctx = {"rdp_username": "ubuntu", "rdp_password": "PerInstancePw!"}
        assert plan.get_context(ctx) is ctx

    def test_unknown_platform_rejected(self):
        from plans.set_local_password import SetLocalPasswordPlan

        with pytest.raises(ValueError, match="Unknown platform"):
            SetLocalPasswordPlan(platform="solaris")
