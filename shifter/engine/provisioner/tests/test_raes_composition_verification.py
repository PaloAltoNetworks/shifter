"""Tests for synchronous in-guest RAES composition verification (#1569)."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from executors.base import CommandResult
from raes_composition_verification import (
    RaesCompositionVerificationOps,
    assert_composition_is_verifiable,
    verify_bootstrap_composition,
)
from raes_gcp_composition import RaesGceCompositionError
from raes_plan import RaesPlan, RaesPlanAccount, RaesPlanContent, RaesPlanNode


def _node(*, os_family: str = "linux", count: int = 2) -> RaesPlanNode:
    return RaesPlanNode(
        address="node.web",
        name="web",
        os_family=os_family,
        count=count,
        network_addresses=("net.lan",),
    )


def _plan(*, node: RaesPlanNode | None = None) -> RaesPlan:
    target = node or _node()
    return RaesPlan(
        raes_version="3.5.0",
        nodes=(target,),
        networks=(),
        content=(
            RaesPlanContent(
                address="content.inline",
                name="inline",
                content_type="file",
                target_address=target.address,
                path="/srv/raes/value.txt",
                text="expected bytes",
                sensitive=True,
            ),
            RaesPlanContent(
                address="content.directory",
                name="directory",
                content_type="directory",
                target_address=target.address,
                destination="/srv/raes/empty",
            ),
        ),
        accounts=(
            RaesPlanAccount(
                address="account.operator",
                username="operator",
                target_address=target.address,
                groups=("ops",),
                login_shell="/bin/bash" if target.os_family == "linux" else None,
                home="/home/operator" if target.os_family == "linux" else None,
                auth_method="password",
            ),
        ),
    )


def _windows_plan() -> RaesPlan:
    plan = _plan(node=_node(os_family="windows", count=1))
    return replace(
        plan,
        content=(
            replace(plan.content[0], path="C:\\raes\\value.txt"),
            replace(plan.content[1], destination="C:\\raes\\empty"),
        ),
    )


def _account_variant_plan(*, os_family: str) -> RaesPlan:
    plan = _windows_plan() if os_family == "windows" else _plan(node=_node(count=1))
    return replace(
        plan,
        accounts=(
            RaesPlanAccount(
                address="account.keyholder",
                username="keyholder",
                target_address=plan.nodes[0].address,
                home="/home/keyholder" if os_family == "linux" else None,
                auth_method="key",
            ),
            RaesPlanAccount(
                address="account.suspended",
                username="suspended",
                target_address=plan.nodes[0].address,
                disabled=True,
            ),
        ),
    )


class _Execution:
    def __init__(self) -> None:
        self.executor = object()
        self.target = "10.60.0.10"
        self.document_name = "AWS-RunShellScript"
        self.wait_for_ready = MagicMock(return_value=True)
        self.close = MagicMock()


def _outputs(count: int = 2) -> list[dict[str, str]]:
    return [{"uuid": f"node.web#{index}", "private_ip": f"10.60.0.{10 + index}"} for index in range(count)]


def test_verifies_every_bootstrap_item_on_every_concrete_instance() -> None:
    executions: list[_Execution] = []
    orchestrators: list[MagicMock] = []

    def execution_builder(*_args, **_kwargs):
        execution = _Execution()
        executions.append(execution)
        return execution

    def orchestrator_factory(_executor):
        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = SimpleNamespace(verification_result=SimpleNamespace(success=True))
        orchestrators.append(orchestrator)
        return orchestrator

    verified = verify_bootstrap_composition(
        _plan(),
        _outputs(),
        RaesCompositionVerificationOps(
            execution_builder=execution_builder,
            orchestrator_factory=orchestrator_factory,
        ),
    )

    assert verified == frozenset({"content.inline", "content.directory", "account.operator"})
    assert len(orchestrators) == 2
    assert all(execution.wait_for_ready.called for execution in executions)
    assert all(execution.close.called for execution in executions)
    rendered = orchestrators[0].orchestrate.call_args.args[1].verify_step.script
    assert "sha256sum" in rendered
    assert "stat -c '%u:%g:%a'" in rendered
    assert "0:0:600" in rendered
    assert "getent passwd" in rendered
    assert "RAES_COMPOSITION_VERIFIED" in rendered
    assert "expected bytes" not in rendered


def test_linux_probe_verifies_public_key_permissions_and_disabled_state() -> None:
    plan = _account_variant_plan(os_family="linux")
    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = SimpleNamespace(verification_result=SimpleNamespace(success=True))

    verified = verify_bootstrap_composition(
        plan,
        _outputs(count=1),
        RaesCompositionVerificationOps(
            execution_builder=lambda *_args, **_kwargs: _Execution(),
            orchestrator_factory=lambda _executor: orchestrator,
        ),
    )

    assert verified == frozenset({"content.inline", "content.directory", "account.keyholder", "account.suspended"})
    rendered = orchestrator.orchestrate.call_args.args[1].verify_step.script
    assert "account_home=$(getent passwd keyholder | cut -d: -f6)" in rendered
    assert 'test -s "$account_home/.ssh/authorized_keys"' in rendered
    assert '"$account_home/.ssh" 2>/dev/null)" = 700' in rendered
    assert '"$account_home/.ssh/authorized_keys" 2>/dev/null)" = 600' in rendered
    assert "passwd -S suspended" in rendered
    assert "grep -Eq '^(L|LK)$'" in rendered


def test_one_failed_fanout_instance_prevents_all_evidence() -> None:
    outcomes = iter((True, False))

    def orchestrator_factory(_executor):
        orchestrator = MagicMock()
        orchestrator.orchestrate.return_value = SimpleNamespace(
            verification_result=SimpleNamespace(success=next(outcomes))
        )
        return orchestrator

    plan = _plan()
    outputs = _outputs()
    ops = RaesCompositionVerificationOps(
        execution_builder=lambda *_args, **_kwargs: _Execution(),
        orchestrator_factory=orchestrator_factory,
    )
    with pytest.raises(RaesGceCompositionError, match="in-guest verification failed"):
        verify_bootstrap_composition(plan, outputs, ops)


def test_real_setup_orchestrator_failure_is_converted_to_bounded_verification_error(monkeypatch) -> None:
    executor = MagicMock()
    executor.run_command.return_value = CommandResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="guest state diverged",
    )
    execution = _Execution()
    execution.executor = executor
    monkeypatch.setattr("orchestrators.setup_orchestrator.time.sleep", lambda _seconds: None)
    plan = _plan(node=_node(count=1))
    outputs = _outputs(count=1)
    ops = RaesCompositionVerificationOps(
        execution_builder=lambda *_args, **_kwargs: execution,
    )

    with pytest.raises(RaesGceCompositionError, match="in-guest verification failed"):
        verify_bootstrap_composition(plan, outputs, ops)

    assert executor.run_command.call_count == 5
    execution.close.assert_called_once()


def test_missing_instance_output_fails_with_value_free_error() -> None:
    plan = _plan()
    outputs = _outputs(count=1)
    ops = RaesCompositionVerificationOps(
        execution_builder=lambda *_args, **_kwargs: _Execution(),
        orchestrator_factory=MagicMock(),
    )
    with pytest.raises(RaesGceCompositionError) as exc_info:
        verify_bootstrap_composition(plan, outputs, ops)
    assert "node.web#1" not in str(exc_info.value)


@pytest.mark.parametrize(
    "outputs",
    [
        [*_outputs(), {"uuid": "node.web#1", "private_ip": "10.60.0.99"}],
        [*_outputs(), {"uuid": "node.extra#0", "private_ip": "10.60.0.99"}],
    ],
)
def test_duplicate_or_extra_instance_output_fails_exact_fanout_coverage(outputs) -> None:
    plan = _plan()
    orchestrator = MagicMock(
        orchestrate=MagicMock(return_value=SimpleNamespace(verification_result=SimpleNamespace(success=True)))
    )
    ops = RaesCompositionVerificationOps(
        execution_builder=lambda *_args, **_kwargs: _Execution(),
        orchestrator_factory=lambda _executor: orchestrator,
    )
    with pytest.raises(RaesGceCompositionError, match="instance output coverage is invalid"):
        verify_bootstrap_composition(plan, outputs, ops)


def test_windows_shell_or_home_is_rejected_before_mutation() -> None:
    node = _node(os_family="windows", count=1)
    plan = RaesPlan(
        raes_version="3.5.0",
        nodes=(node,),
        networks=(),
        accounts=(
            RaesPlanAccount(
                address="account.operator",
                username="operator",
                target_address=node.address,
                login_shell="powershell.exe",
            ),
        ),
    )

    with pytest.raises(RaesGceCompositionError, match="unsupported account attributes"):
        assert_composition_is_verifiable(plan)


def test_source_less_file_without_inline_bytes_is_not_overclaimed() -> None:
    node = _node(count=1)
    plan = RaesPlan(
        raes_version="3.5.0",
        nodes=(node,),
        networks=(),
        content=(
            RaesPlanContent(
                address="content.empty-file",
                name="empty-file",
                content_type="file",
                target_address=node.address,
                path="/srv/empty",
            ),
        ),
    )

    with pytest.raises(RaesGceCompositionError, match="unsupported content shape"):
        assert_composition_is_verifiable(plan)


def test_windows_plan_checks_real_file_directory_account_and_acl_state() -> None:
    plan = _windows_plan()
    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = SimpleNamespace(verification_result=SimpleNamespace(success=True))

    verify_bootstrap_composition(
        plan,
        _outputs(count=1),
        RaesCompositionVerificationOps(
            execution_builder=lambda *_args, **_kwargs: _Execution(),
            orchestrator_factory=lambda _executor: orchestrator,
        ),
    )

    verify_step = orchestrator.orchestrate.call_args.args[1].verify_step
    assert verify_step.stdin_input
    assert "C:\\raes\\value.txt" not in verify_step.script
    assert "operator" not in verify_step.script
    assert "Get-FileHash" in verify_step.script
    assert "ReparsePoint" in verify_step.script
    assert "Get-LocalUser" in verify_step.script
    assert "AreAccessRulesProtected" in verify_step.script
    assert ".GetOwner([System.Security.Principal.SecurityIdentifier]).Value" in verify_step.script
    assert "$ExpectedSids" in verify_step.script
    assert "$AllowRules" in verify_step.script
    assert "$DenyRules" in verify_step.script
    assert "FileSystemRights]::FullControl" in verify_step.script


def test_windows_probe_verifies_public_key_and_disabled_account_state() -> None:
    plan = _account_variant_plan(os_family="windows")
    orchestrator = MagicMock()
    orchestrator.orchestrate.return_value = SimpleNamespace(verification_result=SimpleNamespace(success=True))

    verified = verify_bootstrap_composition(
        plan,
        _outputs(count=1),
        RaesCompositionVerificationOps(
            execution_builder=lambda *_args, **_kwargs: _Execution(),
            orchestrator_factory=lambda _executor: orchestrator,
        ),
    )

    assert verified == frozenset({"content.inline", "content.directory", "account.keyholder", "account.suspended"})
    verify_step = orchestrator.orchestrate.call_args.args[1].verify_step
    payload = json.loads(base64.b64decode(verify_step.stdin_input).decode())
    assert payload["accounts"] == [
        {"username": "keyholder", "groups": [], "disabled": False, "auth_method": "key"},
        {"username": "suspended", "groups": [], "disabled": True, "auth_method": "password"},
    ]
    assert "$User.Enabled -ne (-not [bool]$Account.disabled)" in verify_step.script
    assert "$Account.auth_method -eq 'key'" in verify_step.script
    assert "authorized_keys" in verify_step.script
    assert "AreAccessRulesProtected" in verify_step.script


def test_windows_probe_crosses_the_static_script_and_stdin_executor_boundary() -> None:
    executor = MagicMock()
    executor.run_command.return_value = CommandResult(
        success=True,
        exit_code=0,
        stdout="RAES_COMPOSITION_VERIFIED",
        stderr="",
    )
    execution = _Execution()
    execution.executor = executor
    execution.document_name = "AWS-RunPowerShellScript"

    verified = verify_bootstrap_composition(
        _windows_plan(),
        _outputs(count=1),
        RaesCompositionVerificationOps(
            execution_builder=lambda *_args, **_kwargs: execution,
        ),
    )

    assert verified == frozenset({"content.inline", "content.directory", "account.operator"})
    command = executor.run_command.call_args
    assert command.kwargs["document_name"] == "AWS-RunPowerShellScript"
    assert command.kwargs["stdin_input"]
    assert "C:\\raes\\value.txt" not in command.kwargs["script"]
    assert "operator" not in command.kwargs["script"]
