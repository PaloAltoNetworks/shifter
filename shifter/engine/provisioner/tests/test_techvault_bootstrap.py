"""Tests for the TechVault range bootstrap plan and the is_techvault gate."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _Ctx:
    """Context shim for TechVaultRangeBootstrapPlan.get_context."""

    def __init__(self, model=None, small_fast=None):
        if model is not None:
            self.anthropic_model = model
        if small_fast is not None:
            self.anthropic_small_fast_model = small_fast


class TestTechVaultRangeBootstrapPlan:
    def test_single_bedrock_shard_step_plus_verify(self):
        from plans.techvault_range_bootstrap import TechVaultRangeBootstrapPlan

        plan = TechVaultRangeBootstrapPlan()
        assert [s.name for s in plan.steps] == ["techvault_bedrock_shard"]
        assert plan.verify_step is not None
        assert plan.verify_step.name == "verify_techvault_range"
        assert plan.verify_step.is_verification is True

    def test_shard_script_writes_host_profile_and_verify_checks_claude(self):
        from plans.techvault_range_bootstrap import TechVaultRangeBootstrapPlan

        plan = TechVaultRangeBootstrapPlan()
        shard = plan.steps[0].script
        assert "/etc/profile.d/claude-bedrock.sh" in shard
        assert "CLAUDE_CODE_USE_BEDROCK=1" in shard
        # No container copy: the seat is the host, not a container.
        assert "docker cp" not in shard
        verify = plan.verify_step.script
        assert "command -v claude" in verify

    def test_get_context_defaults_to_bedrock_models(self, monkeypatch):
        from plans.techvault_range_bootstrap import TechVaultRangeBootstrapPlan

        for var in (
            "TECHVAULT_ANTHROPIC_MODEL",
            "ANTHROPIC_MODEL",
            "TECHVAULT_ANTHROPIC_SMALL_FAST_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
            "AWS_REGION",
        ):
            monkeypatch.delenv(var, raising=False)
        ctx = TechVaultRangeBootstrapPlan().get_context(_Ctx())
        assert ctx["anthropic_model"] == "us.anthropic.claude-sonnet-4-6"
        assert ctx["anthropic_small_fast_model"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        assert ctx["aws_region"] == "us-east-2"

    def test_get_context_honors_env_overrides(self, monkeypatch):
        from plans.techvault_range_bootstrap import TechVaultRangeBootstrapPlan

        monkeypatch.setenv("TECHVAULT_ANTHROPIC_MODEL", "us.anthropic.custom-model")
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        ctx = TechVaultRangeBootstrapPlan().get_context(_Ctx())
        assert ctx["anthropic_model"] == "us.anthropic.custom-model"
        assert ctx["aws_region"] == "us-west-2"


class TestIsTechVaultGate:
    def test_techvault_ami_runs_bedrock_shard_and_records_ubuntu(self, monkeypatch):
        from instance_orchestrator import _setup_one_other_instance

        seen = {}

        def record_single_setup(*, instance_data, instance_id, spec):
            seen["ssh_user_override"] = spec.ssh_user_override
            seen["set_local_password"] = spec.set_local_password

        monkeypatch.setattr("instance_orchestrator.get_agent_presigned_url", MagicMock(return_value=""))
        monkeypatch.setattr(
            "instance_orchestrator._run_single_instance_setup",
            MagicMock(side_effect=record_single_setup),
        )
        tv_bootstrap = MagicMock()
        monkeypatch.setattr("instance_orchestrator._run_techvault_range_bootstrap", tv_bootstrap)
        # Polaris path must not fire for a techvault instance.
        polaris = MagicMock()
        monkeypatch.setattr("instance_orchestrator._run_polaris_range_bootstrap", polaris)

        inst = {
            "uuid": "inst-tv",
            "asset_type": "vm_runtime_vm",
            "role": "attacker",
            "os": "kali",
            "instance_id": "i-techvault",
            "hostname": "techvault",
            "name": "techvault",
            "public_key": "ssh-rsa AAAA",
        }
        result = _setup_one_other_instance(
            inst,
            {"inst-tv": {"ami_key": "techvault"}},
            actual_dc_ip=None,
            actual_domain=None,
            range_id=7,
        )

        assert result == ("i-techvault", True, None)
        assert seen["ssh_user_override"] == "ubuntu"
        assert seen["set_local_password"] is True  # host password IS set for techvault
        assert inst["ssh_username"] == "ubuntu"  # portal RDPs as the seat user
        tv_bootstrap.assert_called_once()
        assert tv_bootstrap.call_args.kwargs["instance_id"] == "i-techvault"
        assert tv_bootstrap.call_args.kwargs["range_id"] == 7
        polaris.assert_not_called()

    def test_non_techvault_ami_does_not_run_techvault_bootstrap(self, monkeypatch):
        from instance_orchestrator import _setup_one_other_instance

        monkeypatch.setattr("instance_orchestrator.get_agent_presigned_url", MagicMock(return_value=""))

        def record_single_setup(*, instance_data, instance_id, spec):
            assert spec.ssh_user_override is None

        monkeypatch.setattr(
            "instance_orchestrator._run_single_instance_setup",
            MagicMock(side_effect=record_single_setup),
        )
        tv_bootstrap = MagicMock()
        monkeypatch.setattr("instance_orchestrator._run_techvault_range_bootstrap", tv_bootstrap)
        monkeypatch.setattr("instance_orchestrator._run_polaris_range_bootstrap", MagicMock())

        inst = {
            "uuid": "inst-v",
            "asset_type": "vm_runtime_vm",
            "role": "victim",
            "os": "ubuntu",
            "instance_id": "i-victim",
            "hostname": "victim",
            "name": "victim",
            "public_key": "ssh-rsa AAAA",
        }
        result = _setup_one_other_instance(
            inst,
            {"inst-v": {"ami_key": None}},
            actual_dc_ip=None,
            actual_domain=None,
            range_id=1,
        )

        assert result == ("i-victim", True, None)
        assert "ssh_username" not in inst
        tv_bootstrap.assert_not_called()


class TestRunTechVaultRangeBootstrap:
    def _patch_transport(self, monkeypatch, captured, *, success=True):
        import techvault_bootstrap

        class _FakeExecution:
            executor = MagicMock()
            target = "i-techvault"
            document_name = "AWS-RunShellScript"

            def close(self):
                captured["closed"] = True

        def fake_build_context(instance_data, *, os_type, role):
            captured["os_type"] = os_type
            captured["role"] = role
            return _FakeExecution()

        class _FakeOrchestrator:
            def __init__(self, *, executor):
                captured["executor"] = executor

            def orchestrate(self, target, plan, context, document_name):
                captured["target"] = target
                captured["context"] = context
                captured["plan_steps"] = [s.name for s in plan.steps]
                return SimpleNamespace(success=success, error=None if success else "boom")

        monkeypatch.setattr(techvault_bootstrap, "build_guest_execution_context", fake_build_context)
        monkeypatch.setattr(techvault_bootstrap, "SetupOrchestrator", _FakeOrchestrator)
        return techvault_bootstrap

    def test_orchestrates_bedrock_shard_and_closes(self, monkeypatch):
        captured = {}
        tv = self._patch_transport(monkeypatch, captured)
        tv._run_techvault_range_bootstrap(
            instance_data={"instance_id": "i-techvault", "os": "kali", "role": "attacker"},
            instance_id="i-techvault",
            range_id=5,
        )
        assert captured["target"] == "i-techvault"
        assert captured["plan_steps"] == ["techvault_bedrock_shard"]
        assert captured["context"]["anthropic_model"]
        assert captured["closed"] is True

    def test_raises_setup_error_on_failure(self, monkeypatch):
        from orchestrators.setup_orchestrator import SetupError

        captured = {}
        tv = self._patch_transport(monkeypatch, captured, success=False)
        with pytest.raises(SetupError, match="techvault range bootstrap failed"):
            tv._run_techvault_range_bootstrap(
                instance_data={"instance_id": "i-techvault", "os": "kali", "role": "attacker"},
                instance_id="i-techvault",
            )
        assert captured["closed"] is True
