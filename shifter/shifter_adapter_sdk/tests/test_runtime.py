"""Reject replay, target escalation and ambiguous worker messages."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from shifter_adapter_sdk.runtime import (
    MAX_OUTPUT_BYTES,
    PROTOCOL,
    GuestAction,
    InspectionInput,
    PluginManifest,
    RuntimeInput,
    RuntimePlan,
    parse_input,
    parse_result,
)
from shifter_adapter_sdk.worker import inspect_invocation, main, plan_invocation


@pytest.fixture
def manifest():
    return PluginManifest(
        protocol=PROTOCOL,
        plugin_id="example.adapter",
        version="1.0",
        distribution="example-adapter",
        entry_point="example",
        worker_image="registry.example.test/adapters/example@sha256:" + "a" * 64,
        capabilities=["guest.configure", "guest.verify"],
        required_bindings=["server"],
    )


@pytest.fixture
def request_input(manifest):
    return RuntimeInput(
        protocol=PROTOCOL,
        invocation_id=uuid4(),
        operation_id=uuid4(),
        pack_digest="sha256:" + "b" * 64,
        manifest=manifest,
        phase="verify",
        provider="gcp",
        range_id=1,
        targets={"server": {"node_address": "node.example", "os_family": "linux"}},
    )


def plan(request, **changes):
    data = dict(
        protocol=PROTOCOL,
        invocation_id=request.invocation_id,
        input_digest=request.digest,
        phase=request.phase,
        status="planned",
        actions=[GuestAction(action_id="ready", binding="server", script="test -f /tmp/ready")],
    )
    data.update(changes)
    return RuntimePlan(**data)


def install_entry(monkeypatch, plugin, *, version="1.0", duplicate=False):
    entry = SimpleNamespace(
        dist=SimpleNamespace(name="example_adapter", version=version),
        name="example",
        load=lambda: lambda: plugin,
    )
    entries = [entry, entry] if duplicate else [entry]
    monkeypatch.setattr(
        "shifter_adapter_sdk.worker.importlib.metadata.entry_points",
        lambda: SimpleNamespace(select=lambda **kwargs: entries),
    )


def test_round_trip_keeps_host_target_and_input_identity(request_input):
    request = parse_input(request_input.model_dump_json())
    response = parse_result(plan(request).model_dump_json(), request)
    assert response.status == "planned"
    assert response.actions[0].binding == "server"


@pytest.mark.parametrize("changed", ["invocation_id", "operation_id", "pack_digest", "range_id", "phase", "targets"])
def test_cannot_replay_into_changed_authority(request_input, changed):
    response = plan(request_input).model_dump_json()
    data = request_input.model_dump(mode="json")
    data[changed] = {
        "invocation_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "pack_digest": "sha256:" + "c" * 64,
        "range_id": 2,
        "phase": "configure",
        "targets": {"server": {"node_address": "node.other", "os_family": "linux"}},
    }[changed]
    with pytest.raises(ValueError):
        parse_result(response, RuntimeInput.model_validate(data))


@pytest.mark.parametrize("raw", [b"\xff", '{"phase":"inspect","phase":"verify"}', '{"x":NaN}', "{} {}"])
def test_input_rejects_ambiguous_messages(raw):
    with pytest.raises(ValueError):
        parse_input(raw)


def test_raw_output_bound_applies_before_whitespace_normalization(request_input):
    with pytest.raises(ValueError):
        parse_result(" " * MAX_OUTPUT_BYTES + plan(request_input).model_dump_json(), request_input)


def test_worker_cannot_add_a_target_or_cloud_authority(request_input):
    data = plan(request_input).model_dump(mode="json")
    data["actions"][0]["binding"] = "another-range"
    with pytest.raises(ValueError):
        parse_result(json.dumps(data), request_input)
    data["actions"][0]["binding"] = "server"
    data["actions"][0]["role_arn"] = "unapproved"
    with pytest.raises(ValueError):
        parse_result(json.dumps(data), request_input)


def test_empty_verification_and_failed_actions_cannot_claim_success(request_input):
    with pytest.raises(ValueError):
        plan(request_input, actions=[])
    with pytest.raises(ValueError):
        plan(request_input, status="failed", failure_code="planning-failed")


def test_aggregate_action_budget_is_enforced(request_input):
    with pytest.raises(ValueError):
        plan(
            request_input,
            actions=[
                GuestAction(action_id=f"step-{i}", binding="server", script="true", timeout_seconds=300)
                for i in range(5)
            ],
        )


@pytest.mark.parametrize("version,duplicate", [("2.0", False), ("1.0", True)])
def test_missing_or_ambiguous_distribution_is_not_loaded(monkeypatch, request_input, version, duplicate):
    def never(_request):
        pytest.fail("incompatible distribution was loaded")

    install_entry(monkeypatch, SimpleNamespace(plan=never), version=version, duplicate=duplicate)
    result = plan_invocation(request_input)
    assert result.status == "failed"
    assert result.actions == []


def test_mutating_input_does_not_rebind_worker_result(monkeypatch, request_input):
    original_digest = request_input.digest

    def mutate(request):
        request.targets["server"] = request.targets["server"].model_copy(update={"node_address": "node.other"})
        return plan(request)

    install_entry(monkeypatch, SimpleNamespace(plan=mutate))
    result = plan_invocation(request_input)
    assert result.status == "failed"
    assert result.input_digest == original_digest


def test_mutated_plan_is_revalidated(monkeypatch, request_input):
    def mutate(request):
        response = plan(request)
        response.actions.clear()
        return response

    install_entry(monkeypatch, SimpleNamespace(plan=mutate))
    assert plan_invocation(request_input).status == "failed"


def test_installation_probe_needs_no_fake_range(monkeypatch, manifest):
    install_entry(monkeypatch, SimpleNamespace(plan=lambda _: None))
    request = InspectionInput(protocol=PROTOCOL, invocation_id=uuid4(), phase="inspect", manifest=manifest)
    result = inspect_invocation(request)
    assert parse_result(result.model_dump_json(), request).status == "compatible"
    assert "targets" not in request.model_dump()


def test_worker_does_not_emit_plugin_diagnostics(monkeypatch, capsys, request_input):
    def broken(_request):
        print("private diagnostic")
        raise ValueError("private exception")

    install_entry(monkeypatch, SimpleNamespace(plan=broken))
    monkeypatch.setenv("SHIFTER_PLUGIN_INPUT", request_input.model_dump_json())
    assert main() == 1
    captured = capsys.readouterr()
    assert "private" not in captured.out + captured.err
    assert parse_result(captured.out, request_input).failure_code == "planning-failed"


@pytest.mark.parametrize("field", ["private_key", "credential_ref", "public_key", "role_arn"])
def test_runtime_values_cannot_select_secret_or_arbitrary_fields(request_input, field):
    with pytest.raises(ValueError):
        GuestAction(
            action_id="configure",
            binding="server",
            script="true",
            runtime_values={"value": {"binding": "server", "field": field}},
        )


def test_runtime_value_reference_cannot_escape_original_guest_bindings(request_input):
    response = plan(
        request_input,
        actions=[
            GuestAction(
                action_id="configure",
                binding="server",
                script="true",
                runtime_values={"address": {"binding": "foreign", "field": "private_address"}},
            )
        ],
    )
    with pytest.raises(ValueError, match="authorized invocation"):
        parse_result(response.model_dump_json(), request_input)
