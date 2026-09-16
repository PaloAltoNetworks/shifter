"""Tests for SetLocalPasswordPlan (#762)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSetLocalPasswordPlan:
    """The plan that pushes per-instance guest credentials post-boot."""

    def test_linux_step_reads_password_from_runtime_stdin_not_script_or_argv(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="linux")
        assert len(plan.steps) == 1
        step = plan.steps[0]

        assert "IFS= read -r password" in step.script
        assert "printf '%s:%s" in step.script
        assert '"$ssh_user" "$password" | "${CHPASSWD_CMD[@]}"' in step.script
        assert "{{ rdp_password }}" not in step.script
        assert step.stdin_input == "{{ rdp_password }}\n"

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
        assert "[Console]::In.ReadToEnd()" in step.script
        assert "{{ rdp_password }}" not in step.script
        assert step.stdin_input == "{{ rdp_password }}\n"

    def test_linux_verify_step_checks_user_password_status(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="linux")
        assert plan.verify_step is not None
        assert plan.verify_step.is_verification is True
        assert "passwd -S" in plan.verify_step.script

    def test_linux_container_step_sets_password_inside_target_container(self):
        from plans.set_local_password import SetLocalPasswordPlan

        plan = SetLocalPasswordPlan(platform="linux", target_container="a14-kali")
        step = plan.steps[0]

        assert 'container="{{ rdp_container_name }}"' in step.script
        assert 'docker exec -i "$container" chpasswd' in step.script
        assert "{{ rdp_password }}" not in step.script
        assert step.stdin_input == "{{ rdp_password }}\n"

        context = plan.get_context({"rdp_username": "kali", "rdp_password": "PerInstancePw!"})
        assert context["rdp_container_name"] == "a14-kali"

        verify = plan.verify_step
        assert 'docker exec "$container" passwd -S "$ssh_user"' in verify.script

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

    def test_container_target_rejected_for_windows(self):
        from plans.set_local_password import SetLocalPasswordPlan

        with pytest.raises(ValueError, match="target_container"):
            SetLocalPasswordPlan(platform="windows", target_container="a14-kali")
