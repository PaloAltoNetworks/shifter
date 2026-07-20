"""Tests for ACES authored-account credential strategy dispatch (#1560)."""

from dataclasses import replace
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock, call

import pytest

from aces_account_credentials import (
    AcesAccountCredentialError,
    AcesAccountCredentialOps,
    delete_instance_account_credentials,
    install_instance_account_credentials,
)
from aces_plan import AcesPlanAccount
from plans.set_authorized_key import SetAuthorizedKeyPlan
from plans.set_local_password import SetLocalPasswordPlan


def _account(**overrides) -> AcesPlanAccount:
    values = {
        "username": "alice",
        "target_address": "node.web",
        "auth_method": "password",
        "password_strength": "medium",
    }
    values.update(overrides)
    return AcesPlanAccount(**values)


def _ops() -> tuple[AcesAccountCredentialOps, SimpleNamespace]:
    calls = SimpleNamespace(
        ensure_password=MagicMock(return_value=("projects/p/secrets/password", "SECRET-PASSWORD")),
        ensure_public_key=MagicMock(return_value=("projects/p/secrets/key", "ssh-rsa PUBLIC")),
        delete=MagicMock(),
    )
    return (
        AcesAccountCredentialOps(
            ensure_password=calls.ensure_password,
            ensure_public_key=calls.ensure_public_key,
            delete=calls.delete,
        ),
        calls,
    )


class _Execution:
    def __init__(self):
        self.executor = object()
        self.target = "10.9.0.10"
        self.document_name = "AWS-RunShellScript"
        self.wait_for_ready = MagicMock(return_value=True)
        self.close = MagicMock()


class _Orchestrator:
    instances: ClassVar[list["_Orchestrator"]] = []

    def __init__(self, executor):
        self.executor = executor
        self.calls: list[tuple[object, dict]] = []
        self.instances.append(self)

    def orchestrate(self, target, plan, context, document_name):
        self.calls.append((plan, context))
        return SimpleNamespace(success=True)


def test_password_strategy_generates_by_strength_and_reuses_password_plan():
    ops, calls = _ops()
    execution = _Execution()
    _Orchestrator.instances.clear()
    ops = replace(
        ops,
        execution_builder=lambda *_args, **_kwargs: execution,
        orchestrator_factory=_Orchestrator,
    )

    result = install_instance_account_credentials(
        range_id=7,
        instance_key="node.web#0",
        platform="linux",
        instance_output={"private_ip": execution.target},
        accounts=(_account(password_strength="strong"),),
        secret_ops=ops,
    )

    assert result is None
    calls.ensure_password.assert_called_once_with(7, "node.web#0", "alice", "strong")
    plan, context = _Orchestrator.instances[0].calls[0]
    assert isinstance(plan, SetLocalPasswordPlan)
    assert context == {"rdp_username": "alice", "rdp_password": "SECRET-PASSWORD"}
    execution.wait_for_ready.assert_called_once()
    execution.close.assert_called_once()


def test_public_key_strategy_uses_account_specific_plan():
    ops, calls = _ops()
    execution = _Execution()
    _Orchestrator.instances.clear()
    ops = replace(
        ops,
        execution_builder=lambda *_args, **_kwargs: execution,
        orchestrator_factory=_Orchestrator,
    )

    install_instance_account_credentials(
        range_id=7,
        instance_key="node.web#0",
        platform="windows",
        instance_output={"private_ip": execution.target},
        accounts=(_account(auth_method="publickey"),),
        secret_ops=ops,
    )

    calls.ensure_public_key.assert_called_once_with(7, "node.web#0", "alice")
    plan, context = _Orchestrator.instances[0].calls[0]
    assert isinstance(plan, SetAuthorizedKeyPlan)
    assert context == {"account_username_quoted": "'alice'", "account_public_key": "ssh-rsa PUBLIC"}


def test_disabled_accounts_never_generate_or_install_credentials():
    ops, calls = _ops()
    execution_builder = MagicMock()
    ops = replace(
        ops,
        execution_builder=execution_builder,
        orchestrator_factory=_Orchestrator,
    )

    install_instance_account_credentials(
        range_id=7,
        instance_key="node.web#0",
        platform="linux",
        instance_output={},
        accounts=(_account(disabled=True),),
        secret_ops=ops,
    )

    calls.ensure_password.assert_not_called()
    calls.ensure_public_key.assert_not_called()
    execution_builder.assert_not_called()


def test_failure_is_coarse_and_execution_is_closed():
    ops, _calls = _ops()
    execution = _Execution()

    class FailingOrchestrator(_Orchestrator):
        def orchestrate(self, target, plan, context, document_name):
            raise RuntimeError("SECRET-PASSWORD")

    ops = replace(
        ops,
        execution_builder=lambda *_args, **_kwargs: execution,
        orchestrator_factory=FailingOrchestrator,
    )

    account = _account()
    with pytest.raises(AcesAccountCredentialError) as exc_info:
        install_instance_account_credentials(
            range_id=7,
            instance_key="node.web#0",
            platform="linux",
            instance_output={"private_ip": execution.target},
            accounts=(account,),
            secret_ops=ops,
        )

    assert "SECRET-PASSWORD" not in str(exc_info.value)
    assert exc_info.value.__suppress_context__ is True
    assert "alice" in str(exc_info.value)
    execution.close.assert_called_once()


def test_management_channel_failure_is_coarse_and_execution_is_closed():
    ops, _calls = _ops()
    execution = _Execution()
    execution.wait_for_ready.side_effect = RuntimeError("provider-payload-SECRET-PASSWORD")
    ops = replace(
        ops,
        execution_builder=lambda *_args, **_kwargs: execution,
        orchestrator_factory=_Orchestrator,
    )

    account = _account()
    with pytest.raises(AcesAccountCredentialError) as exc_info:
        install_instance_account_credentials(
            range_id=7,
            instance_key="node.web#0",
            platform="linux",
            instance_output={"private_ip": execution.target},
            accounts=(account,),
            secret_ops=ops,
        )

    assert str(exc_info.value) == "failed to establish credential setup channel for instance 'node.web#0'"
    assert exc_info.value.__suppress_context__ is True
    execution.close.assert_called_once()


def test_destroy_deletes_each_authored_account_secret():
    ops, calls = _ops()
    accounts = (_account(), _account(username="bob", auth_method="publickey", disabled=True))

    delete_instance_account_credentials(7, "node.web#0", accounts, ops)

    assert calls.delete.call_args_list == [
        call(7, "node.web#0", "alice", "password"),
        call(7, "node.web#0", "bob", "publickey"),
    ]
