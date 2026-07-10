"""Behavior tests for the run_post_deploy_smoke management command."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

import cms.management.commands.run_post_deploy_smoke as smoke_command
from cms.post_deploy_smoke import probe as probe_module
from cms.post_deploy_smoke.probe import probe_rdp_endpoint, tcp_reachable
from shared.enums import ResourceStatus

User = get_user_model()


def _range_context(*, status=ResourceStatus.READY, instances=None):
    if instances is None:
        instances = [SimpleNamespace(role="attacker", uuid=str(uuid4()))]
    return SimpleNamespace(status=status, instances=instances)


@pytest.fixture
def smoke_user(db):
    return User.objects.create_user(username="smoke", email="smoke@test.example", password="x")


@pytest.fixture
def fast_clock(monkeypatch):
    """Advance monotonic time so polling loops exit quickly in tests."""
    now = {"value": 1000.0}

    def monotonic() -> float:
        now["value"] += 30.0
        return now["value"]

    monkeypatch.setattr(smoke_command.time, "monotonic", monotonic)
    monkeypatch.setattr(smoke_command.time, "sleep", lambda *_args, **_kwargs: None)


@pytest.fixture
def smoke_command_mocks(monkeypatch):
    from unittest.mock import MagicMock

    mocks = SimpleNamespace(
        cms=MagicMock(),
        probe_ssh=MagicMock(),
        probe_rdp=MagicMock(),
        ssh_info=MagicMock(),
        rdp_info=MagicMock(),
    )
    monkeypatch.setattr(smoke_command, "cms_services", mocks.cms)
    monkeypatch.setattr(smoke_command, "probe_ssh_endpoint", mocks.probe_ssh)
    monkeypatch.setattr(smoke_command, "probe_rdp_endpoint", mocks.probe_rdp)
    monkeypatch.setattr(smoke_command, "get_ssh_connection_info", mocks.ssh_info)
    monkeypatch.setattr(smoke_command, "get_rdp_connection_info", mocks.rdp_info)
    # Both variants now resolve agents (basic's from_agent victim requires one),
    # so provide the agent IDs the variants read. create_range is mocked, so the
    # values are inert.
    monkeypatch.setenv("SMOKE_LINUX_AGENT_ID", "43")
    monkeypatch.setenv("SMOKE_WINDOWS_AGENT_ID", "42")
    return mocks


def test_run_post_deploy_smoke_success(
    smoke_user,
    monkeypatch,
    fast_clock,
    smoke_command_mocks,
) -> None:
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", smoke_user.email)
    request_id = uuid4()
    smoke_command_mocks.cms.create_range.return_value = SimpleNamespace(request_id=str(request_id))
    smoke_command_mocks.cms.find_range_instance_id_by_request.return_value = 1
    smoke_command_mocks.cms.get_range_status_by_id.return_value = ResourceStatus.READY.value
    smoke_command_mocks.cms.get_range_by_request_id.return_value = _range_context()
    smoke_command_mocks.ssh_info.return_value = {"host": "10.0.0.1", "port": 22}

    call_command("run_post_deploy_smoke", "--variant", "linux", "--poll-interval", "1")

    smoke_command_mocks.cms.destroy_range_by_request_id.assert_called_once_with(
        smoke_user,
        str(request_id),
    )
    smoke_command_mocks.probe_ssh.assert_called_once_with("10.0.0.1", 22)


def test_run_post_deploy_smoke_missing_user_email(monkeypatch) -> None:
    monkeypatch.delenv("SMOKE_TEST_USER_EMAIL", raising=False)
    with pytest.raises(CommandError, match="SMOKE_TEST_USER_EMAIL"):
        call_command("run_post_deploy_smoke")


def test_run_post_deploy_smoke_creates_missing_user(
    monkeypatch,
    fast_clock,
    smoke_command_mocks,
    db,
) -> None:
    email = "smoke-dev@test.example"
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", email)
    assert User.objects.filter(email__iexact=email).count() == 0
    request_id = uuid4()
    smoke_command_mocks.cms.create_range.return_value = SimpleNamespace(request_id=str(request_id))
    smoke_command_mocks.cms.find_range_instance_id_by_request.return_value = 1
    smoke_command_mocks.cms.get_range_status_by_id.return_value = ResourceStatus.READY.value
    smoke_command_mocks.cms.get_range_by_request_id.return_value = _range_context()
    smoke_command_mocks.ssh_info.return_value = {"host": "10.0.0.1", "port": 22}

    call_command("run_post_deploy_smoke", "--variant", "linux", "--poll-interval", "1")

    user = User.objects.get(email__iexact=email)
    smoke_command_mocks.cms.create_range.assert_called_once()
    assert smoke_command_mocks.cms.create_range.call_args[0][0] == user


def test_run_post_deploy_smoke_provision_timeout(
    smoke_user,
    monkeypatch,
    fast_clock,
    smoke_command_mocks,
) -> None:
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", smoke_user.email)
    request_id = uuid4()
    smoke_command_mocks.cms.create_range.return_value = SimpleNamespace(request_id=str(request_id))
    smoke_command_mocks.cms.find_range_instance_id_by_request.return_value = None

    with pytest.raises(CommandError, match="timed out"):
        call_command("run_post_deploy_smoke", "--variant", "linux", "--poll-interval", "1")

    smoke_command_mocks.cms.destroy_range_by_request_id.assert_called_once()


def test_run_post_deploy_smoke_connectivity_failure(
    smoke_user,
    monkeypatch,
    fast_clock,
    smoke_command_mocks,
) -> None:
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", smoke_user.email)
    request_id = uuid4()
    smoke_command_mocks.cms.create_range.return_value = SimpleNamespace(request_id=str(request_id))
    smoke_command_mocks.cms.find_range_instance_id_by_request.return_value = 1
    smoke_command_mocks.cms.get_range_status_by_id.return_value = ResourceStatus.READY.value
    smoke_command_mocks.cms.get_range_by_request_id.return_value = _range_context()
    smoke_command_mocks.ssh_info.return_value = {"host": "10.0.0.1", "port": 22}
    smoke_command_mocks.probe_ssh.side_effect = RuntimeError("down")

    with pytest.raises(CommandError, match="connectivity probe failed"):
        call_command("run_post_deploy_smoke", "--variant", "linux", "--poll-interval", "1")

    smoke_command_mocks.cms.destroy_range_by_request_id.assert_called_once()


def test_run_post_deploy_smoke_create_range_without_request_id(
    smoke_user,
    monkeypatch,
    smoke_command_mocks,
) -> None:
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", smoke_user.email)
    smoke_command_mocks.cms.create_range.return_value = SimpleNamespace(request_id=None)

    with pytest.raises(CommandError, match="no request_id"):
        call_command("run_post_deploy_smoke", "--variant", "linux")


def test_run_post_deploy_smoke_windows_rdp_path(
    smoke_user,
    monkeypatch,
    fast_clock,
    smoke_command_mocks,
) -> None:
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", smoke_user.email)
    monkeypatch.setenv("SMOKE_WINDOWS_AGENT_ID", "42")
    monkeypatch.setenv("SMOKE_LINUX_AGENT_ID", "43")
    request_id = uuid4()
    windows_uuid = str(uuid4())
    smoke_command_mocks.cms.create_range.return_value = SimpleNamespace(request_id=str(request_id))
    smoke_command_mocks.cms.find_range_instance_id_by_request.return_value = 1
    smoke_command_mocks.cms.get_range_status_by_id.return_value = ResourceStatus.READY.value
    smoke_command_mocks.cms.get_range_by_request_id.return_value = _range_context(
        instances=[
            SimpleNamespace(role="attacker", uuid=str(uuid4())),
            SimpleNamespace(role="dc", uuid=windows_uuid),
        ]
    )
    smoke_command_mocks.rdp_info.return_value = {"host": "10.0.0.5", "port": 3389}

    call_command("run_post_deploy_smoke", "--variant", "windows", "--poll-interval", "1")

    smoke_command_mocks.probe_rdp.assert_called_once_with("10.0.0.5", 3389)


def test_run_post_deploy_smoke_range_not_ready_for_probe(
    smoke_user,
    monkeypatch,
    fast_clock,
    smoke_command_mocks,
) -> None:
    monkeypatch.setenv("SMOKE_TEST_USER_EMAIL", smoke_user.email)
    request_id = uuid4()
    smoke_command_mocks.cms.create_range.return_value = SimpleNamespace(request_id=str(request_id))
    smoke_command_mocks.cms.find_range_instance_id_by_request.return_value = 1
    smoke_command_mocks.cms.get_range_status_by_id.return_value = ResourceStatus.READY.value
    smoke_command_mocks.cms.get_range_by_request_id.return_value = _range_context(status=ResourceStatus.PROVISIONING)

    with pytest.raises(CommandError, match="not READY for connectivity probe"):
        call_command("run_post_deploy_smoke", "--variant", "linux", "--poll-interval", "1")


def test_tcp_reachable_success(monkeypatch) -> None:
    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(probe_module.socket, "create_connection", lambda *_args, **_kwargs: _Conn())
    assert tcp_reachable("127.0.0.1", 1) is True


def test_probe_rdp_endpoint_success() -> None:
    probe_rdp_endpoint("10.0.0.2", 3389, connect_fn=lambda _h, _p, _t: True)
