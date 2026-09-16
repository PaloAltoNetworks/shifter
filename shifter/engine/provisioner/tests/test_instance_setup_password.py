"""Secret-safe guest-password transport tests (#1790)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import instance_password_setup as password_setup
import instance_setup
from executors.base import ExecutorError
from orchestrators.setup_orchestrator import SetupError


def _execution(*, stdout: str = "") -> password_setup.GuestExecutionContext:
    executor = MagicMock()
    executor.run_command.return_value = SimpleNamespace(success=True, stdout=stdout)
    return password_setup.GuestExecutionContext(
        executor=executor,
        target="i-0123456789",
        document_name="AWS-RunPowerShellScript",
        transport_name="ssm",
    )


def test_resolves_password_from_active_secret_store(monkeypatch):
    secrets_store = MagicMock()
    secrets_store.get_secret.return_value = "runtime-password"
    monkeypatch.setattr("cloud.get_secrets_store", lambda: secrets_store)

    assert password_setup._resolve_rdp_password_from_secret_ref(None) is None
    assert password_setup._resolve_rdp_password_from_secret_ref("arn:guest-password") == "runtime-password"
    secrets_store.get_secret.assert_called_once_with("arn:guest-password")


@pytest.mark.parametrize(
    ("platform", "expected_script"),
    [
        ("windows", password_setup._WINDOWS_SSH_HOST_KEY_SCRIPT),
        ("linux", password_setup._LINUX_SSH_HOST_KEY_SCRIPT),
    ],
)
def test_reads_and_normalizes_ssh_host_key_over_ssm(platform, expected_script):
    execution = _execution(stdout="noise\nSHIFTER_SSH_HOST_KEY=ssh-ed25519 AAAATEST guest@host\n")

    result = password_setup._read_aws_ssh_host_key_or_raise(
        execution,
        platform=platform,
        failure_prefix="password push failed",
    )

    assert result == "ssh-ed25519 AAAATEST"
    execution.executor.run_command.assert_called_once_with(
        execution.target,
        expected_script,
        timeout_seconds=60,
        document_name=execution.document_name,
    )


def test_rejects_missing_or_non_ed25519_ssh_host_key():
    execution = _execution(stdout="SHIFTER_SSH_HOST_KEY=ssh-rsa AAAATEST\n")

    with pytest.raises(SetupError, match="valid ed25519 SSH host key"):
        password_setup._read_aws_ssh_host_key_or_raise(
            execution,
            platform="windows",
            failure_prefix="password push failed",
        )


def test_host_key_read_wraps_executor_error():
    execution = _execution()
    execution.executor.run_command.side_effect = ExecutorError("offline")

    with pytest.raises(SetupError, match="could not read the SSH host key over SSM"):
        password_setup._read_aws_ssh_host_key_or_raise(
            execution,
            platform="windows",
            failure_prefix="password push failed",
        )


@pytest.mark.parametrize(
    "instance_data",
    [
        {"ssh_key_secret_arn": "arn:ssh-key"},
        {"private_ip": "10.20.30.40"},
    ],
)
def test_aws_password_execution_requires_ip_and_key_reference(instance_data):
    execution = _execution()

    with pytest.raises(SetupError, match="missing private_ip or ssh_key_secret_arn"):
        password_setup._build_aws_password_execution_or_raise(
            execution,
            instance_data,
            ssh_user="Administrator",
            platform="windows",
            failure_prefix="password push failed",
        )


def _patch_aws_password_execution_dependencies(monkeypatch, ssh_executor):
    monkeypatch.setattr(password_setup, "_read_aws_ssh_host_key_or_raise", lambda *_a, **_kw: "ssh-ed25519 KEY")
    secrets_store = MagicMock()
    secrets_store.get_secret.return_value = "PRIVATE KEY"
    monkeypatch.setattr("cloud.get_secrets_store", lambda: secrets_store)
    constructor = MagicMock(return_value=ssh_executor)
    monkeypatch.setattr("executors.guest_ssh_executor.GuestSSHExecutor", constructor)
    return constructor


def test_builds_ready_host_key_pinned_aws_password_execution(monkeypatch):
    ssh_executor = MagicMock()
    constructor = _patch_aws_password_execution_dependencies(monkeypatch, ssh_executor)

    result = password_setup._build_aws_password_execution_or_raise(
        _execution(),
        {"private_ip": "10.20.30.40", "ssh_key_secret_arn": "arn:ssh-key"},
        ssh_user="Administrator",
        platform="windows",
        failure_prefix="password push failed",
    )

    assert result.target == "10.20.30.40"
    assert result.transport_name == "pinned-ssh"
    constructor.assert_called_once_with(
        private_key="PRIVATE KEY",
        username="Administrator",
        host_public_key="ssh-ed25519 KEY",
        known_hosts_host="10.20.30.40",
    )
    ssh_executor.wait_for_ready.assert_called_once_with(
        "10.20.30.40",
        timeout_seconds=120,
        document_name="AWS-RunPowerShellScript",
    )


def test_closes_aws_password_execution_when_ssh_never_becomes_ready(monkeypatch):
    ssh_executor = MagicMock()
    ssh_executor.wait_for_ready.side_effect = ExecutorError("offline")
    _patch_aws_password_execution_dependencies(monkeypatch, ssh_executor)
    execution = _execution()
    instance_data = {"private_ip": "10.20.30.40", "ssh_key_secret_arn": "arn:ssh-key"}

    with pytest.raises(SetupError, match="pinned SSH transport did not become ready"):
        password_setup._build_aws_password_execution_or_raise(
            execution,
            instance_data,
            ssh_user="Administrator",
            platform="windows",
            failure_prefix="password push failed",
        )

    ssh_executor.close.assert_called_once_with()


def test_aws_password_push_uses_secret_value_on_separate_ssh_execution(monkeypatch):
    original_execution = _execution()
    password_executor = MagicMock()
    password_execution = password_setup.GuestExecutionContext(
        executor=password_executor,
        target="10.20.30.40",
        document_name="AWS-RunPowerShellScript",
        transport_name="pinned-ssh",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(password_setup, "_get_cloud_provider", lambda: "aws")
    monkeypatch.setattr(
        password_setup,
        "_build_aws_password_execution_or_raise",
        lambda *_args, **_kwargs: password_execution,
    )
    monkeypatch.setattr(
        password_setup,
        "_resolve_rdp_password_from_secret_ref",
        lambda ref: "Real-Runtime-Password!" if ref == "arn:guest-password" else None,
    )

    def capture_run(orchestrator, execution, plan, context, failure_prefix):
        captured.update(
            orchestrator=orchestrator,
            execution=execution,
            plan=plan,
            context=context,
            failure_prefix=failure_prefix,
        )

    monkeypatch.setattr(password_setup, "_run_password_plan", capture_run)

    password_setup.set_local_password_or_raise(
        MagicMock(),
        original_execution,
        {
            "private_ip": "10.20.30.40",
            "ssh_key_secret_arn": "arn:ssh-key",
            "rdp_password_secret_arn": "arn:guest-password",
        },
        ssh_user="Administrator",
        platform="windows",
        failure_prefix="password push failed",
    )

    assert captured["execution"] is password_execution
    assert captured["context"] == {
        "rdp_username": "Administrator",
        "rdp_password": "Real-Runtime-Password!",
    }
    plan = captured["plan"]
    assert "Real-Runtime-Password!" not in plan.steps[0].script
    assert plan.steps[0].stdin_input == "{{ rdp_password }}\n"
    password_executor.close.assert_called_once_with()


def test_gcp_password_push_reuses_existing_execution_and_bootstrap_secret(monkeypatch):
    execution = _execution()
    orchestrator = MagicMock()
    run_plan = MagicMock()
    monkeypatch.setattr(password_setup, "_get_cloud_provider", lambda: "gcp")
    resolve = MagicMock(return_value="runtime-password")
    monkeypatch.setattr(password_setup, "_resolve_rdp_password_from_secret_ref", resolve)
    monkeypatch.setattr(password_setup, "_run_password_plan", run_plan)

    password_setup.set_local_password_or_raise(
        orchestrator,
        execution,
        {
            "gcp_bootstrap_rdp_password_secret_ref": "projects/p/secrets/bootstrap",
            "rdp_password_secret_arn": "projects/p/secrets/runtime",
        },
        ssh_user="kali",
        platform="linux",
        failure_prefix="password push failed",
        target_container="desktop",
    )

    resolve.assert_called_once_with("projects/p/secrets/bootstrap")
    assert run_plan.call_args.args[0] is orchestrator
    assert run_plan.call_args.args[1] is execution
    execution.executor.close.assert_not_called()


def test_password_push_closes_owned_execution_when_secret_is_empty(monkeypatch):
    password_executor = MagicMock()
    password_execution = password_setup.GuestExecutionContext(
        executor=password_executor,
        target="10.20.30.40",
        document_name="AWS-RunPowerShellScript",
        transport_name="pinned-ssh",
    )
    monkeypatch.setattr(password_setup, "_get_cloud_provider", lambda: "aws")
    monkeypatch.setattr(
        password_setup,
        "_build_aws_password_execution_or_raise",
        lambda *_args, **_kwargs: password_execution,
    )
    monkeypatch.setattr(password_setup, "_resolve_rdp_password_from_secret_ref", lambda _ref: "")
    instance_data = {"rdp_password_secret_arn": "arn:guest-password"}
    orchestrator = MagicMock()
    execution = _execution()

    with pytest.raises(SetupError, match="password fetch returned empty"):
        password_setup.set_local_password_or_raise(
            orchestrator,
            execution,
            instance_data,
            ssh_user="Administrator",
            platform="windows",
            failure_prefix="password push failed",
        )

    password_executor.close.assert_called_once_with()


def test_password_push_requires_secrets_manager_reference(monkeypatch):
    monkeypatch.setattr(password_setup, "_get_cloud_provider", lambda: "aws")
    execution = _execution()
    orchestrator = MagicMock()
    instance_data = {"rdp_password_ssm_param_name": "/obsolete/placeholder"}

    with pytest.raises(SetupError, match="no RDP secret reference"):
        password_setup.set_local_password_or_raise(
            orchestrator,
            execution,
            instance_data,
            ssh_user="Administrator",
            platform="windows",
            failure_prefix="password push failed",
        )


def test_password_plan_failure_is_a_setup_error():
    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = SimpleNamespace(success=False, error="denied")
    execution = _execution()
    plan = password_setup.SetLocalPasswordPlan(platform="windows")

    with pytest.raises(SetupError, match="password push failed: denied"):
        password_setup._run_password_plan(
            orchestrator,
            execution,
            plan,
            {"rdp_username": "Administrator", "rdp_password": "runtime-password"},
            "password push failed",
        )


def test_instance_setup_wrapper_passes_only_context_username(monkeypatch):
    push = MagicMock()
    monkeypatch.setattr(instance_setup, "_push_local_password_or_raise", push)
    execution = _execution()
    orchestrator = MagicMock()
    instance_data = {"rdp_password_secret_arn": "arn:guest-password"}
    ctx = instance_setup._InstanceSetupCtx("workstation", "public-key", "", "Administrator")

    instance_setup._set_local_password_or_raise(
        orchestrator,
        execution,
        ctx,
        instance_data,
        platform="windows",
        failure_prefix="password push failed",
    )

    push.assert_called_once_with(
        orchestrator,
        execution,
        instance_data,
        ssh_user="Administrator",
        platform="windows",
        failure_prefix="password push failed",
        target_container=None,
    )
