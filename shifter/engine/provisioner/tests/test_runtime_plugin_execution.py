"""An isolated worker's output grants actions only on original guest bindings."""

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.raes.operation_input import (
    RaesInputBindings,
    RaesRangeIdentity,
    build_raes_operation_input,
    parse_raes_operation_input,
)
from shared.runtime_plugin_binding import RuntimePluginPin, runtime_plugin_requests
from shifter_adapter_sdk.runtime import RuntimePlan

import runtime_plugin_execution as execution
from executors.base import CommandResult
from provisioner_db_operation_input import RaesOperationRun


@pytest.fixture
def run():
    pin = RuntimePluginPin(
        pack_id="example",
        installation_id=uuid4(),
        organization_uuid=uuid4(),
        pack_digest="sha256:" + "a" * 64,
        manifest={
            "protocol": "shifter.runtime-plugin/v1",
            "plugin_id": "example.adapter",
            "version": "1",
            "distribution": "example-adapter",
            "entry_point": "example",
            "worker_image": "registry.example.test/adapter@sha256:" + "b" * 64,
            "capabilities": ["guest.configure", "guest.verify"],
            "required_bindings": ["server"],
        },
        bindings={"targets": {"server": "node.web"}},
    )
    plan = {"resources": {"node.web": {"resource_type": "node", "payload": {"os_family": "linux", "spec": {}}}}}
    payload = build_raes_operation_input(
        plan=plan,
        bindings=RaesInputBindings(delivery=(), runtime_plugin=pin),
        image_candidates={},
        range_backend="gce",
        instantiation_purpose="live_fire",
        identity=RaesRangeIdentity(7, None),
    )
    return RaesOperationRun(str(uuid4()), str(uuid4()), parse_raes_operation_input(payload))


@pytest.fixture
def database(run, monkeypatch):
    from uuid import UUID

    requests = runtime_plugin_requests(run.input.runtime_plugin, run.input.plan, UUID(run.operation_id), 7)
    rows = {}
    for request in requests:
        result = RuntimePlan(
            protocol=request.protocol,
            invocation_id=request.invocation_id,
            phase=request.phase,
            input_digest=request.digest,
            status="planned",
            actions=[]
            if request.phase == "validate"
            else [
                {"action_id": request.phase, "binding": "server", "script": f"# {request.phase}\nexit 0"},
            ],
        )
        rows[str(request.invocation_id)] = ["planned", request.digest, result.model_dump(mode="json")]
    cursor = MagicMock()
    cursor.execute.side_effect = lambda sql, args: setattr(cursor, "selected", args[0])
    cursor.fetchone.side_effect = lambda: rows.get(cursor.selected)
    connection = MagicMock()
    connection.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(execution, "get_db_connection", lambda: connection)
    return SimpleNamespace(rows=rows, requests=requests, cursor=cursor)


@pytest.fixture
def guest(monkeypatch):
    context = MagicMock()
    context.target = "host-selected-by-core"
    context.document_name = "AWS-RunShellScript"
    context.wait_for_ready.return_value = True
    context.executor.run_command.return_value = CommandResult(True, 0, "private-output", "")
    builder = MagicMock(return_value=context)
    monkeypatch.setattr(execution, "build_guest_execution_context", builder)
    return SimpleNamespace(context=context, builder=builder)


def test_plans_round_trip_then_execute_configure_and_verify_only_on_original_guest(run, database, guest, caplog):
    caplog.set_level(logging.INFO)
    bundle = execution.load_guest_plugin_plans(run)
    output = {"uuid": "node.web#0", "private_ip": "10.0.0.7", "credential_ref": "host-only"}
    bundle.execute(None, [output])
    assert guest.builder.call_count == 2
    assert all(call.args == (output,) for call in guest.builder.call_args_list)
    assert guest.context.executor.run_command.call_count == 2
    # The first action may be the first contact with a slow-booting guest (e.g. a
    # pre-promoted DC), so each action allows the standard node-readiness bound.
    assert all(call.kwargs == {"timeout_seconds": 300} for call in guest.context.wait_for_ready.call_args_list)
    assert guest.context.close.call_count == 2
    assert "private-output" not in caplog.text
    assert "Runtime plugin guest action completed ordinal=2" in caplog.text
    assert "Runtime plugin guest phase preparing phase=configure" in caplog.text
    assert [plan.phase for plan in bundle.plans] == ["validate", "configure", "verify"]
    assert all(request.targets["server"].private_address == "" for request in bundle.requests)


@pytest.mark.parametrize("tamper", ["operation", "target", "phase", "failure", "empty-proof"])
def test_invalid_result_set_is_rejected_before_guest_execution(run, database, guest, tamper):
    row = database.rows[str(database.requests[-1].invocation_id)]
    if tamper == "operation":
        row[2]["invocation_id"] = str(uuid4())
    elif tamper == "target":
        row[2]["actions"][0]["binding"] = "foreign"
    elif tamper == "phase":
        row[2]["phase"] = "configure"
    elif tamper == "failure":
        row[0] = "failed"
    else:
        row[2]["actions"] = []
    with pytest.raises(execution.RuntimePluginExecutionError, match="planning failed"):
        execution.load_guest_plugin_plans(run)
    guest.builder.assert_not_called()


def test_missing_guest_rejects_the_whole_plan_before_any_action(run, database, guest):
    bundle = execution.load_guest_plugin_plans(run)
    with pytest.raises(execution.RuntimePluginExecutionError):
        bundle.execute(None, [{"uuid": "node.other#0"}])
    guest.builder.assert_not_called()


def test_guest_failure_closes_transport_hides_diagnostics_and_skips_verification(run, database, guest, caplog):
    caplog.set_level(logging.INFO)
    bundle = execution.load_guest_plugin_plans(run)
    guest.context.executor.run_command.side_effect = RuntimeError("private-script-and-key")
    with pytest.raises(execution.RuntimePluginExecutionError) as error:
        bundle.execute(None, [{"uuid": "node.web#0"}])
    assert guest.builder.call_count == 1
    guest.context.close.assert_called_once()
    assert "private-script-and-key" not in str(error.value) + caplog.text
    assert "Runtime plugin guest action starting ordinal=1" in caplog.text
    assert "Runtime plugin guest action completed ordinal=1" not in caplog.text


def test_guest_nonzero_exit_logs_only_bounded_result_fields(run, database, guest, caplog):
    caplog.set_level(logging.INFO)
    bundle = execution.load_guest_plugin_plans(run)
    guest.context.executor.run_command.return_value = CommandResult(False, 42, "private-output", "private-error")
    with pytest.raises(execution.RuntimePluginExecutionError):
        bundle.execute(None, [{"uuid": "node.web#0"}])
    assert "Runtime plugin guest action failed ordinal=1 success=False exit_code=42" in caplog.text
    assert "private-output" not in caplog.text
    assert "private-error" not in caplog.text
    guest.context.close.assert_called_once()


def test_pending_planning_has_a_deadline_and_never_executes_guests(run, database, guest, monkeypatch):
    for row in database.rows.values():
        row[0] = "pending"
    clock = iter([0, 1, 601])
    monkeypatch.setattr(execution.time, "monotonic", lambda: next(clock))
    wait = MagicMock()
    monkeypatch.setattr(execution.time, "sleep", wait)
    with pytest.raises(execution.RuntimePluginExecutionError, match="timed out"):
        execution.load_guest_plugin_plans(run)
    wait.assert_called_once_with(2)
    guest.builder.assert_not_called()


def test_runtime_addresses_resolve_from_host_guest_map(run, database, guest):
    import base64
    import json

    for row in database.rows.values():
        for action in row[2]["actions"]:
            action["runtime_values"] = {"address": {"binding": "server", "field": "private_address"}}
    bundle = execution.load_guest_plugin_plans(run)
    bundle.execute(None, [{"uuid": "node.web#0", "private_ip": "10.0.0.7", "public_key": "management"}])
    script = guest.context.executor.run_command.call_args.args[1]
    encoded = script.split("SHIFTER_RUNTIME_VALUES_B64='")[1].split("'")[0]
    assert json.loads(base64.b64decode(encoded)) == {"address": "10.0.0.7"}
    assert "management" not in script


def test_missing_value_in_last_action_prevents_all_guest_execution(run, database, guest):
    row = database.rows[str(database.requests[-1].invocation_id)]
    row[2]["actions"][0]["runtime_values"] = {"address": {"binding": "server", "field": "private_address"}}
    bundle = execution.load_guest_plugin_plans(run)
    with pytest.raises(execution.RuntimePluginExecutionError):
        bundle.execute(None, [{"uuid": "node.web#0", "private_ip": "invalid"}])
    guest.builder.assert_not_called()


def test_missing_participant_declaration_rejects_before_provisioning(run, database, guest):
    row = database.rows[str(database.requests[-1].invocation_id)]
    row[2]["actions"][0]["runtime_values"] = {
        "key": {"binding": "server", "field": "participant_ssh_public_key"},
    }
    with pytest.raises(execution.RuntimePluginExecutionError, match="planning failed"):
        execution.load_guest_plugin_plans(run)
    guest.builder.assert_not_called()


def test_participant_key_never_falls_back_to_management_key(database):
    import base64
    import json

    from shifter_adapter_sdk.runtime import GuestAction

    from runtime_plugin_values import resolve_runtime_values
    from utils.crypto import generate_ssh_keypair

    _, public_key = generate_ssh_keypair()
    public_key = public_key.strip()
    action = GuestAction(
        action_id="configure",
        binding="server",
        script="true",
        runtime_values={
            "key": {"binding": "server", "field": "participant_ssh_public_key"},
        },
    )
    output = {"public_key": public_key, "participant_access_channels": ["ssh"]}
    with pytest.raises(ValueError, match="Participant public key"):
        resolve_runtime_values(action, database.requests[1], {"node.web#0": output})
    output["participant_ssh_public_key"] = public_key
    data = resolve_runtime_values(action, database.requests[1], {"node.web#0": output})
    assert json.loads(base64.b64decode(data)) == {"key": public_key}
    output["participant_access_channels"] = []
    with pytest.raises(ValueError):
        resolve_runtime_values(action, database.requests[1], {"node.web#0": output})


def test_linux_wrapper_preserves_literal_data_exit_status_and_suppresses_output(tmp_path):
    import base64
    import json
    import subprocess

    marker = tmp_path / "executed"
    value = f"$(touch {marker})'\"; exit 12; #"
    data = base64.b64encode(json.dumps({"literal": value}).encode()).decode()
    script = (
        "python3 - <<'PY'\nimport os, json, base64\n"
        "v=json.loads(base64.b64decode(os.environ['SHIFTER_RUNTIME_VALUES_B64']))\n"
        "assert v['literal'].startswith('$(touch ')\nprint('private output')\nPY\nexit 7\n"
    )
    result = subprocess.run(  # noqa: S603 -- execute the wrapper against synthetic adversarial data
        ["/bin/bash", "-c", execution._quiet_script(script, "linux", data)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 7
    assert not result.stdout and not result.stderr
    assert not marker.exists()
