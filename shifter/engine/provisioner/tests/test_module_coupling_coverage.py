"""Focused coverage for provisioner module-boundary coupling."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class RecordingCursor:
    def __init__(
        self,
        *,
        fetchone: Any | list[Any] | None = None,
        fetchall: list[Any] | None = None,
        rowcounts: list[int] | None = None,
    ) -> None:
        self.execute_calls: list[tuple[Any, Any]] = []
        self._fetchone_values = fetchone if isinstance(fetchone, list) else [fetchone]
        self._fetchall = fetchall or []
        self._rowcounts = rowcounts or [1]
        self.rowcount = 0

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, query: Any, params: Any = None) -> None:
        self.execute_calls.append((query, params))
        self.rowcount = self._rowcounts.pop(0) if self._rowcounts else self.rowcount

    def fetchone(self) -> Any:
        return self._fetchone_values.pop(0) if self._fetchone_values else None

    def fetchall(self) -> list[Any]:
        return self._fetchall


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor) -> None:
        self._cursor = cursor
        self.commit = MagicMock()

    def __enter__(self) -> RecordingConnection:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def cursor(self) -> RecordingCursor:
        return self._cursor


def _install_cloud_secret_store(monkeypatch: pytest.MonkeyPatch, private_key: str = "private-key") -> MagicMock:
    get_secret = MagicMock(return_value=private_key)
    secrets = SimpleNamespace(get_secret=get_secret)
    cloud = ModuleType("cloud")
    cloud.get_secrets_store = MagicMock(return_value=secrets)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "cloud", cloud)
    return get_secret


def test_dc_setup_uses_agent_asset_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    from instance_orchestrator import _setup_dc_instances_blocking

    run_dc_setup = MagicMock()
    get_agent_url = MagicMock(return_value="https://signed.example/agent.msi")
    monkeypatch.setattr("instance_orchestrator._run_dc_setup", run_dc_setup)
    monkeypatch.setattr("instance_orchestrator.get_agent_presigned_url", get_agent_url)

    _setup_dc_instances_blocking(
        [
            {
                "uuid": "dc-uuid",
                "instance_id": "i-dc",
                "private_ip": "10.1.0.10",
                "public_key": "ssh-rsa AAAA",
            }
        ],
        {"dc-uuid": {"dc_config": {"domain_name": "range.local"}, "agent": {"s3_key": "agents/xdr.msi"}}},
    )

    get_agent_url.assert_called_once_with(
        {"dc_config": {"domain_name": "range.local"}, "agent": {"s3_key": "agents/xdr.msi"}}
    )
    run_dc_setup.assert_called_once_with(
        instance_data={
            "uuid": "dc-uuid",
            "instance_id": "i-dc",
            "private_ip": "10.1.0.10",
            "public_key": "ssh-rsa AAAA",
        },
        instance_id="i-dc",
        dc_config={"domain_name": "range.local"},
        agent_presigned_url="https://signed.example/agent.msi",
        public_key="ssh-rsa AAAA",
        xdr_required=True,
    )


def test_attacker_container_password_uses_guest_execution_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from instance_setup import _set_attacker_container_password_after_bootstrap

    execution = SimpleNamespace(
        executor=object(),
        target="i-polaris",
        transport_name="SSM",
        document_name="AWS-RunShellScript",
        wait_for_ready=MagicMock(),
        close=MagicMock(),
    )
    orchestrator = object()
    set_password = MagicMock()
    monkeypatch.setattr("instance_setup.build_guest_execution_context", MagicMock(return_value=execution))
    monkeypatch.setattr("instance_setup.SetupOrchestrator", MagicMock(return_value=orchestrator))
    monkeypatch.setattr("instance_setup._set_local_password_or_raise", set_password)

    _set_attacker_container_password_after_bootstrap(
        {"hostname": "kali", "public_key": "ssh-rsa AAAA"},
        "i-polaris",
        container_name="a14-kali",
    )

    execution.wait_for_ready.assert_called_once_with(timeout_seconds=120)
    execution.close.assert_called_once_with()
    assert set_password.call_args.args[0] is orchestrator
    assert set_password.call_args.args[1] is execution
    assert set_password.call_args.kwargs["target_container"] == "a14-kali"


def test_windows_victim_setup_uses_bootstrap_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from instance_setup import _DomainJoinSpec, _InstanceSetupCtx, _setup_windows_victim

    class FakeBootstrapPlan:
        def get_context(self, ctx: Any) -> dict[str, str]:
            return {"hostname": ctx.hostname}

    run_setup_plan = MagicMock()
    monkeypatch.setattr("instance_setup.BootstrapPlan", FakeBootstrapPlan)
    monkeypatch.setattr("instance_setup._run_setup_plan", run_setup_plan)
    monkeypatch.setattr("instance_setup._set_local_password_or_raise", MagicMock())
    monkeypatch.setattr("instance_setup._install_xdr_or_raise", MagicMock())
    monkeypatch.setattr("instance_setup._join_windows_domain", MagicMock())

    _setup_windows_victim(
        orchestrator=object(),
        execution=SimpleNamespace(target="i-win", document_name="AWS-RunPowerShellScript"),
        ctx=_InstanceSetupCtx(
            hostname="victim-win",
            public_key="ssh-rsa AAAA",
            agent_presigned_url="",
            ssh_user="Administrator",
        ),
        instance_data={"hostname": "victim-win"},
        agent_presigned_url="",
        xdr_required=False,
        dj=_DomainJoinSpec(join_domain=False, dc_ip=None, domain_name=None),
    )

    assert isinstance(run_setup_plan.call_args.args[2], FakeBootstrapPlan)
    assert run_setup_plan.call_args.args[3] == {"hostname": "victim-win"}


def test_run_single_instance_setup_builds_orchestrator_from_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from instance_setup import _DomainJoinSpec, _InstanceSetupSpec, _run_single_instance_setup

    execution = SimpleNamespace(
        executor=object(),
        target="i-victim",
        transport_name="SSM",
        wait_for_ready=MagicMock(),
        close=MagicMock(),
    )
    dispatch = MagicMock()
    monkeypatch.setattr("instance_setup.build_guest_execution_context", MagicMock(return_value=execution))
    monkeypatch.setattr("instance_setup.SetupOrchestrator", MagicMock(return_value=object()))
    monkeypatch.setattr("instance_setup._dispatch_instance_setup_role", dispatch)

    result = _run_single_instance_setup(
        {"hostname": "victim", "public_key": "ssh-rsa AAAA"},
        "i-victim",
        _InstanceSetupSpec(
            role="victim",
            os_type="ubuntu",
            public_key="ssh-rsa AAAA",
            agent_presigned_url="",
            xdr_required=False,
            instance_name="victim",
            range_id=0,
            domain_join=_DomainJoinSpec(join_domain=False, dc_ip=None, domain_name=None),
        ),
    )

    assert result is True
    execution.wait_for_ready.assert_called_once_with(timeout_seconds=300)
    execution.close.assert_called_once_with()
    assert dispatch.call_args.args[1] is execution


def test_update_instance_state_writes_ngfw_instance_and_app(monkeypatch: pytest.MonkeyPatch) -> None:
    from ngfw_runtime import update_instance_state

    cursor = RecordingCursor(fetchone=(10, {"existing": "value"}, 20))
    conn = RecordingConnection(cursor)
    monkeypatch.setattr("ngfw_runtime.get_db_connection", MagicMock(return_value=conn))

    update_instance_state("ngfw-req", "ready", management_ip="10.1.0.10")

    assert cursor.execute_calls[0][1] == ("ngfw-req",)
    instance_update = cursor.execute_calls[1][1]
    assert instance_update[0] == "ready"
    assert json.loads(instance_update[1]) == {"existing": "value", "management_ip": "10.1.0.10"}
    assert cursor.execute_calls[2][1] == ("ready", 20)
    conn.commit.assert_called_once_with()


def test_find_stale_routes_by_db_returns_destroyed_range_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    from ngfw_runtime import find_stale_routes_by_db

    cursor = RecordingCursor(fetchall=[])
    monkeypatch.setattr("ngfw_runtime.get_db_connection", MagicMock(return_value=RecordingConnection(cursor)))
    ssh_executor = SimpleNamespace(
        run_command=MagicMock(
            return_value=SimpleNamespace(
                success=True,
                stdout="range-42-attack { destination 10.1.2.0/28; }",
            )
        )
    )

    stale_routes = find_stale_routes_by_db(ssh_executor, "10.1.0.10", current_range_id=7)

    assert stale_routes == ["range-42-attack"]
    assert cursor.execute_calls


def test_configure_ngfw_subnets_builds_dynamic_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from ngfw_runtime import configure_ngfw_subnets

    _install_cloud_secret_store(monkeypatch)
    executor = SimpleNamespace(wait_for_agent=MagicMock())
    orchestrator = SimpleNamespace(orchestrate=MagicMock(return_value=SimpleNamespace(success=True, error=None)))
    monkeypatch.setattr("ngfw_runtime.NGFWExecutor", MagicMock(return_value=executor))
    monkeypatch.setattr("ngfw_runtime.poll_for_serial_number", MagicMock())
    monkeypatch.setattr("ngfw_runtime.wait_for_autocommit", MagicMock())
    monkeypatch.setattr("ngfw_runtime.find_stale_routes_by_cidr", MagicMock(return_value=[]))
    monkeypatch.setattr("ngfw_runtime.find_stale_routes_by_db", MagicMock(return_value=[]))
    monkeypatch.setattr(
        "ngfw_runtime.NGFWConfigureSubnetsPlan",
        MagicMock(return_value=SimpleNamespace(get_steps=MagicMock(return_value=[]))),
    )
    monkeypatch.setattr("ngfw_runtime.SetupOrchestrator", MagicMock(return_value=orchestrator))

    configure_ngfw_subnets(
        subnets=[{"name": "attack", "cidr": "10.1.2.0/28"}],
        range_id=42,
        management_ip="10.1.0.10",
        ssh_key_secret_arn="secret-arn",
        route_next_hop_ip="10.1.0.1",
    )

    plan = orchestrator.orchestrate.call_args.kwargs["plan"]
    assert plan.name == "ngfw_configure_subnets"
    assert plan.steps == []


def test_remove_ngfw_subnets_builds_dynamic_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    from ngfw_runtime import remove_ngfw_subnets

    _install_cloud_secret_store(monkeypatch)
    executor = SimpleNamespace(wait_for_agent=MagicMock())
    orchestrator = SimpleNamespace(orchestrate=MagicMock(return_value=SimpleNamespace(success=True, error=None)))
    monkeypatch.setattr(
        "ngfw_runtime.get_user_ngfw_data",
        MagicMock(
            return_value={
                "ngfw_request_id": "ngfw-req",
                "management_ip": "10.1.0.10",
                "ssh_key_secret_arn": "secret-arn",
                "status": "ready",
            }
        ),
    )
    monkeypatch.setattr("ngfw_runtime.NGFWExecutor", MagicMock(return_value=executor))
    monkeypatch.setattr("ngfw_runtime.poll_for_serial_number", MagicMock())
    monkeypatch.setattr(
        "ngfw_runtime.NGFWRemoveSubnetsPlan",
        MagicMock(return_value=SimpleNamespace(get_steps=MagicMock(return_value=[]))),
    )
    monkeypatch.setattr("ngfw_runtime.SetupOrchestrator", MagicMock(return_value=orchestrator))

    remove_ngfw_subnets(user_id=7, subnets=[{"name": "attack", "cidr": "10.1.2.0/28"}], range_id=42)

    plan = orchestrator.orchestrate.call_args.kwargs["plan"]
    assert plan.name == "ngfw_remove_subnets"
    assert plan.steps == []


def test_gcp_ngfw_operation_marks_failed_on_power_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from ngfw_runtime_ops import _run_gcp_ngfw_operation

    gdc_module = ModuleType("gdc_vmseries_ngfw")
    gdc_module.run_power_operation = MagicMock(side_effect=RuntimeError("power failed"))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gdc_vmseries_ngfw", gdc_module)
    update_state = MagicMock()
    publish_event = MagicMock()
    monkeypatch.setattr("ngfw_runtime_ops.update_instance_state", update_state)
    monkeypatch.setattr("ngfw_runtime_ops.publish_ngfw_event", publish_event)

    with pytest.raises(RuntimeError, match="power failed"):
        _run_gcp_ngfw_operation("start", "ngfw-req", "inst-uuid", "app-uuid", {"cloud_provider": "gcp"})

    assert update_state.call_args_list[-1] == call("ngfw-req", "failed", error_message="power failed")
    assert publish_event.call_args_list[-1].kwargs["status"] == "failed"


def test_aws_ngfw_operation_marks_failed_when_plan_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from ngfw_runtime_ops import _run_aws_ngfw_operation

    class FailingOpsOrchestrator:
        def __init__(self, executor: object) -> None:
            self.executor = executor

        def orchestrate(self, instance_id: str, plan: object, context: dict[str, str]) -> SimpleNamespace:
            return SimpleNamespace(
                success=False,
                step_results=[SimpleNamespace(success=False, step_name="stop", stderr="denied")],
            )

    update_state = MagicMock()
    publish_event = MagicMock()
    monkeypatch.setattr("ngfw_runtime_ops.AWSExecutor", MagicMock(return_value=object()))
    monkeypatch.setattr("ngfw_runtime_ops.OpsOrchestrator", FailingOpsOrchestrator)
    monkeypatch.setattr("ngfw_runtime_ops._load_ngfw_ops_plan", MagicMock(return_value=object()))
    monkeypatch.setattr("ngfw_runtime_ops.update_instance_state", update_state)
    monkeypatch.setattr("ngfw_runtime_ops.publish_ngfw_event", publish_event)

    with pytest.raises(RuntimeError, match="Operation stop failed"):
        _run_aws_ngfw_operation("stop", "ngfw-req", "inst-uuid", "app-uuid", "i-ngfw")

    assert update_state.call_args_list[-1] == call(
        "ngfw-req",
        "failed",
        error_message="Operation stop failed",
    )
    assert publish_event.call_args_list[-1].kwargs["status"] == "failed"


def test_provisioner_db_status_helpers_use_owning_module_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    from provisioner_db import _update_range_config, mark_range_instances_destroyed, update_range_status

    update_cursor = RecordingCursor()
    update_conn = RecordingConnection(update_cursor)
    monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=update_conn))

    update_range_status(42, "failed", error_message="boom", finished_at="NOW()", ignored=None)

    assert update_cursor.execute_calls[0][1] == ["failed", "boom", 42]
    update_conn.commit.assert_called_once_with()

    destroy_cursor = RecordingCursor(rowcounts=[3, 2])
    destroy_conn = RecordingConnection(destroy_cursor)
    monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=destroy_conn))

    assert mark_range_instances_destroyed(42) == (3, 2)
    destroy_conn.commit.assert_called_once_with()

    config_cursor = RecordingCursor()
    config_conn = RecordingConnection(config_cursor)
    monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=config_conn))

    _update_range_config(42, {"subnets": [{"name": "attack", "cidr": "10.1.2.0/28"}]})

    saved_spec, saved_range_id = config_cursor.execute_calls[0][1]
    assert json.loads(saved_spec) == {"subnets": [{"name": "attack", "cidr": "10.1.2.0/28"}]}
    assert saved_range_id == 42
    config_conn.commit.assert_called_once_with()


def test_provisioner_db_ngfw_reads_user_and_request_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from provisioner_db_ngfw import get_ngfw_data_by_request_id, get_user_ngfw_data

    user_cursor = RecordingCursor(
        fetchone=(
            "ngfw-req",
            {
                "management_ip": "10.1.0.10",
                "ssh_key_secret_arn": "secret-arn",
                "data_eni_id": "eni-data",
                "route_next_hop_ip": "10.1.0.1",
                "attached_ranges": [{"range_id": 42}],
            },
            "ready",
        )
    )
    monkeypatch.setattr(
        "provisioner_db_ngfw.get_db_connection",
        MagicMock(return_value=RecordingConnection(user_cursor)),
    )

    user_data = get_user_ngfw_data(7)

    assert user_data == {
        "ngfw_request_id": "ngfw-req",
        "cloud_provider": "aws",
        "ec2_instance_id": None,
        "management_ip": "10.1.0.10",
        "ssh_key_secret_arn": "secret-arn",
        "ssh_key_secret_ref": "secret-arn",
        "dataplane_ip": "",
        "route_next_hop_ip": "10.1.0.1",
        "data_eni_id": "eni-data",
        "data_attachment_id": "eni-data",
        "attachment_mode": "aws-route-table-eni",
        "provider_metadata": {},
        "attached_ranges": [{"range_id": 42}],
        "status": "ready",
    }

    request_cursor = RecordingCursor(
        fetchone=("ngfw-req", "inst-uuid", "app-uuid", {"image": "vmseries"}, {"user_id": 7}, {"ready": True}, "ready")
    )
    monkeypatch.setattr(
        "provisioner_db_ngfw.get_db_connection",
        MagicMock(return_value=RecordingConnection(request_cursor)),
    )

    request_data = get_ngfw_data_by_request_id("ngfw-req")

    assert request_data == {
        "request_id": "ngfw-req",
        "instance_id": "inst-uuid",
        "app_id": "app-uuid",
        "spec": {"image": "vmseries"},
        "app_spec": {"user_id": 7},
        "state": {"ready": True},
        "status": "ready",
    }


def test_range_ngfw_helpers_use_direct_runtime_and_db_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    from terraform_ops import (
        _configure_ngfw_for_range,
        _maybe_pause_user_ngfw,
        _recover_aws_ngfw_stuck_resuming,
        _remove_ngfw_attachments_for_destroy,
        _resume_aws_ngfw_for_provisioning,
        _validate_ngfw_range_attachment,
    )

    run_ngfw_operation = MagicMock()
    monkeypatch.setattr("terraform_ops.run_ngfw_operation", run_ngfw_operation)
    monkeypatch.setattr("terraform_ops.AWSExecutor", MagicMock())
    monkeypatch.setattr("terraform_ops._describe_ec2_state", MagicMock(return_value="stopped"))

    _recover_aws_ngfw_stuck_resuming("i-ngfw", "ngfw-req")
    _resume_aws_ngfw_for_provisioning({"status": "paused", "ngfw_request_id": "ngfw-req"})

    assert run_ngfw_operation.call_args_list[:2] == [
        call("start", "ngfw-req"),
        call("start", "ngfw-req"),
    ]

    ngfw_data = {
        "ngfw_request_id": "ngfw-req",
        "cloud_provider": "aws",
        "management_ip": "10.1.0.10",
        "ssh_key_secret_arn": "secret-arn",
        "route_next_hop_ip": "10.1.0.1",
        "data_attachment_id": "eni-data",
        "attachment_mode": "aws-data-eni",
        "status": "ready",
    }
    monkeypatch.setattr("terraform_ops.get_user_ngfw_data", MagicMock(return_value=ngfw_data))
    configure_subnets = MagicMock()
    record_attachment = MagicMock()
    remove_subnets = MagicMock()
    remove_attachment = MagicMock()
    monkeypatch.setattr("terraform_ops.configure_ngfw_subnets", configure_subnets)
    monkeypatch.setattr("terraform_ops._record_ngfw_range_attachment", record_attachment)
    monkeypatch.setattr("terraform_ops.remove_ngfw_subnets", remove_subnets)
    monkeypatch.setattr("terraform_ops._remove_ngfw_range_attachment", remove_attachment)

    _validate_ngfw_range_attachment({"ngfw": True}, user_id=7)
    _configure_ngfw_for_range(
        request_id="range-req",
        range_id=42,
        user_id=7,
        range_spec={"ngfw": True},
        spec_subnets=[{"name": "attack", "connected_to": ["victim"]}],
        subnets_output={"attack": {"subnet_cidr": "10.1.2.0/28"}},
    )
    _remove_ngfw_attachments_for_destroy(7, 42, {"ngfw": True, "subnets": [{"name": "attack"}]})

    configure_subnets.assert_called_once()
    record_attachment.assert_called_once()
    remove_subnets.assert_called_once_with(7, [{"name": "attack"}], 42)
    remove_attachment.assert_called_once_with(ngfw_request_id="ngfw-req", ngfw_status="ready", range_id=42)

    monkeypatch.setattr("terraform_ops.user_has_active_ranges", MagicMock(return_value=False))
    _maybe_pause_user_ngfw(7, 42)

    assert run_ngfw_operation.call_args_list[-1] == call("stop", "ngfw-req")


def test_terraform_vars_resolve_defaults_and_agent_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from terraform_vars import _resolve_agent_presigned_url, _resolve_instance_type

    monkeypatch.setattr("terraform_vars._get_dc_instance_type", MagicMock(return_value="m6i.large"))
    monkeypatch.setattr("terraform_vars._get_windows_instance_type", MagicMock(return_value="m6i.xlarge"))
    monkeypatch.setattr("terraform_vars._get_victim_instance_type", MagicMock(return_value="t3.medium"))

    assert _resolve_instance_type("dc", "windows", None) == "m6i.large"
    assert _resolve_instance_type("victim", "windows", None) == "m6i.xlarge"
    assert _resolve_instance_type("victim", "ubuntu", None) == "t3.medium"

    generate_url = MagicMock(return_value="https://signed.example/agent.deb")
    monkeypatch.setattr("terraform_vars.generate_presigned_url", generate_url)
    monkeypatch.setenv("AGENT_STORAGE_BUCKET", "agent-assets")

    assert _resolve_agent_presigned_url({"agent": {"s3_key": "agents/xdr.deb"}}) == "https://signed.example/agent.deb"
    generate_url.assert_called_once_with(bucket="agent-assets", key="agents/xdr.deb")
