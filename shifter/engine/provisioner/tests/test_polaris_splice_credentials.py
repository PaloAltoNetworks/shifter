"""Provider-neutral Polaris splice credential health/repair tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import polaris_splice_credentials as subject
from executors.base import CommandResult


class RecordingExecutor:
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int, str]] = []

    def run_command(self, target, script, timeout_seconds=300, document_name="AWS-RunShellScript", stdin_input=None):
        assert stdin_input is None
        self.calls.append((target, script, timeout_seconds, document_name))
        return self.result


def _execution(executor: RecordingExecutor):
    execution = SimpleNamespace(
        executor=executor,
        target="instance-target",
        document_name="AWS-RunShellScript",
        closed=False,
    )
    execution.close = lambda: setattr(execution, "closed", True)
    return execution


def test_check_routes_through_guest_execution_and_returns_bounded_status() -> None:
    executor = RecordingExecutor(CommandResult(True, 0, "splice-credential: healthy\n", ""))
    execution = _execution(executor)

    result = subject.run_polaris_splice_credential_operation(
        {"cloud_provider": "aws", "instance_id": "i-123"},
        repair=False,
        execution_builder=lambda *_args, **_kwargs: execution,
    )

    assert result == subject.PolarisSpliceCredentialResult(status="healthy", repaired=False)
    assert executor.calls == [
        (
            "instance-target",
            "/opt/polaris/libexec/polaris-splice-credential.py host-check --container a14-kali",
            120,
            "AWS-RunShellScript",
        )
    ]
    assert execution.closed is True


def test_repair_uses_same_host_helper_without_restarting_containers() -> None:
    executor = RecordingExecutor(CommandResult(True, 0, "splice-credential: repaired\n", ""))
    execution = _execution(executor)

    result = subject.run_polaris_splice_credential_operation(
        {"cloud_provider": "gcp", "asset_type": "gce_vm", "private_ip": "10.0.0.8"},
        repair=True,
        execution_builder=lambda *_args, **_kwargs: execution,
    )

    assert result.repaired is True
    command = executor.calls[0][1]
    assert command.endswith("host-repair --container a14-kali")
    assert "restart" not in command
    assert execution.closed is True


def test_transport_failure_is_secret_safe() -> None:
    executor = RecordingExecutor(CommandResult(False, 9, "PRIVATE-KEY-BYTES", "encoded-secret"))
    execution = _execution(executor)

    with pytest.raises(subject.PolarisSpliceCredentialError, match="credential check failed") as exc:
        subject.run_polaris_splice_credential_operation(
            {"cloud_provider": "aws", "instance_id": "i-123"},
            repair=False,
            execution_builder=lambda *_args, **_kwargs: execution,
        )

    assert "PRIVATE-KEY-BYTES" not in str(exc.value)
    assert "encoded-secret" not in str(exc.value)
    assert execution.closed is True


def test_request_operation_selects_polaris_host_and_reuses_provider_state(monkeypatch) -> None:
    monkeypatch.setattr(
        subject,
        "get_range_data_by_request_id",
        lambda _request_id: {
            "spec": {
                "subnets": [
                    {
                        "instances": [
                            {"uuid": "ordinary", "ami_key": "ubuntu"},
                            {"uuid": "polaris", "ami_key": "polaris-vm", "os": "ubuntu", "role": "attacker"},
                        ]
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        subject,
        "get_range_instance_ids",
        lambda _request_id: [
            {"uuid": "ordinary", "state": {"cloud_provider": "aws", "instance_id": "i-1"}},
            {"uuid": "polaris", "state": {"cloud_provider": "aws", "instance_id": "i-2"}},
        ],
    )
    seen = []
    monkeypatch.setattr(
        subject,
        "run_polaris_splice_credential_operation",
        lambda instance_data, *, repair: (
            seen.append((instance_data, repair)) or subject.PolarisSpliceCredentialResult("healthy", False)
        ),
    )

    result = subject.run_request_polaris_splice_credential_operation("req-7", repair=False)

    assert result.status == "healthy"
    assert seen == [
        (
            {
                "cloud_provider": "aws",
                "instance_id": "i-2",
                "os": "ubuntu",
                "role": "attacker",
            },
            False,
        )
    ]


def test_request_operation_refuses_non_polaris_range(monkeypatch) -> None:
    monkeypatch.setattr(
        subject,
        "get_range_data_by_request_id",
        lambda _request_id: {"spec": {"subnets": [{"instances": [{"uuid": "ordinary", "ami_key": "ubuntu"}]}]}},
    )
    monkeypatch.setattr(subject, "get_range_instance_ids", lambda _request_id: [])

    with pytest.raises(subject.PolarisSpliceCredentialError, match="does not contain a Polaris host"):
        subject.run_request_polaris_splice_credential_operation("req-7", repair=True)
