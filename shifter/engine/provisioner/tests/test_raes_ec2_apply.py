"""Native AWS launch is gated on guest verification and cleans up failed launches."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import UUID

import pytest

from ec2_network_apply import Ec2NetworkResources
from executors.base import CommandResult
from raes_ec2_apply import RaesEc2ApplyOptions, apply_raes_ec2_range
from raes_ec2_image import resolve_ec2_image
from raes_plan import RaesPlanContent
from tests.test_ec2_range_network import config, topology
from tests.test_raes_ec2_image import candidate, client


def setup(monkeypatch):
    ec2 = client()
    secrets = Mock()
    order = []
    network = Mock(
        side_effect=lambda *args: (
            order.append("network")
            or Ec2NetworkResources(
                {"net.lan": "subnet-" + "0" * 17}, {"node.host": "sg-" + "0" * 17}, "rtb-" + "1" * 17
            )
        )
    )
    monkeypatch.setattr("raes_ec2_apply.ensure_ec2_network", network)
    guest = Mock(
        side_effect=lambda plan, *args: (
            order.append("guest")
            or {
                "uuid": plan.instance_key,
                "instance_id": "i-" + "0" * 17,
                "os": "linux",
                "asset_type": "ec2_vm",
                "private_ip": plan.private_ip,
                "participant_access_channels": [],
                "participant_access_usernames": {},
            }
        )
    )
    monkeypatch.setattr("raes_ec2_apply.ensure_ec2_guest", guest)
    monkeypatch.setattr("raes_ec2_apply.observe_ec2_guest", Mock(side_effect=lambda *args: order.append("substrate")))
    cleanup = Mock(return_value={"outcome": "VERIFIED_ABSENT"})
    monkeypatch.setattr("raes_ec2_apply.destroy_raes_ec2_range", cleanup)
    context = Mock()
    context.wait_for_ready.return_value = True
    context.executor.run_command.return_value = CommandResult(True, 0, "", "")
    options = RaesEc2ApplyOptions(
        config=config(),
        generation=UUID(int=2),
        ec2=ec2,
        secrets=secrets,
        allocated_cidrs={"net.lan": "10.50.1.0/28"},
        execution_builder=Mock(return_value=context),
        model_enrollment=lambda *args: order.append("enrollment"),
        runtime_plugin=lambda *args: order.append("plugin"),
        host_readiness_verifier=lambda outputs, **_kwargs: order.append("readiness"),
        composition_verifier=lambda plan, outputs: (
            order.append("composition") or frozenset(item.address for item in plan.content)
        ),
        operating_system_observer=lambda *args: (
            order.append("os")
            or [{"instance_key": "node.host#0", "family": "linux", "distribution": "ubuntu", "version": "24.04"}]
        ),
    )
    return options, order, cleanup, context, network


def launch(options, plan=None):
    return apply_raes_ec2_range(
        str(UUID(int=1)),
        7,
        plan or topology(),
        lambda node: resolve_ec2_image(node, [candidate(source_version="")]),
        options,
    )


def test_enrollment_precedes_plugin_and_ready_requires_independent_guest_observations(monkeypatch):
    options, order, cleanup, _, _ = setup(monkeypatch)
    result = launch(options)
    # Preconfigured-host readiness runs once the plugin has started the participant container (#2527).
    assert order == ["network", "guest", "enrollment", "plugin", "readiness", "composition", "os", "substrate"]
    assert result["compute_substrates"] == [{"instance_key": "node.host#0", "value": "virtual-machine"}]
    # Each realized instance carries its authored subnet name so the terminal-ready
    # member projection parses (non-empty subnet_name is required, #1710).
    assert [instance["subnet_name"] for instance in result["instances"]] == ["lan"]
    cleanup.assert_not_called()


def test_provider_image_mismatch_fails_before_mutation_or_cleanup(monkeypatch):
    options, order, cleanup, _, network = setup(monkeypatch)
    options.ec2.describe_images.return_value["Images"][0]["Platform"] = "windows"
    with pytest.raises(ValueError):
        launch(options)
    network.assert_not_called()
    cleanup.assert_not_called()
    assert order == []


def test_plugin_failure_runs_owned_cleanup_and_never_reports_ready(monkeypatch):
    options, order, cleanup, _, _ = setup(monkeypatch)
    options = replace(options, runtime_plugin=Mock(side_effect=RuntimeError("private failure")))
    with pytest.raises(RuntimeError):
        launch(options)
    cleanup.assert_called_once()
    assert "os" not in order and "substrate" not in order


def test_inline_content_is_sent_over_management_transport_and_session_always_closes(monkeypatch):
    options, _, cleanup, context, _ = setup(monkeypatch)
    plan = replace(
        topology(),
        content=(
            RaesPlanContent(
                "note", "file", "node.host", address="content.note", path="/etc/range-note", text="synthetic"
            ),
        ),
    )
    launch(options, plan)
    context.wait_for_ready.assert_called_once_with(600)
    assert "/etc/range-note" in context.executor.run_command.call_args.args[1]
    context.close.assert_called_once()
    cleanup.assert_not_called()


def test_bootstrap_failure_closes_management_session_and_attempts_cleanup(monkeypatch):
    options, _, cleanup, context, _ = setup(monkeypatch)
    context.executor.run_command.return_value = CommandResult(False, 1, "", "private guest failure")
    plan = replace(
        topology(),
        content=(
            RaesPlanContent(
                "note", "file", "node.host", address="content.note", path="/etc/range-note", text="synthetic"
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="bootstrap failed") as caught:
        launch(options, plan)
    assert "private guest failure" not in str(caught.value)
    context.close.assert_called_once()
    cleanup.assert_called_once()


def test_os_readback_mismatch_cannot_return_success(monkeypatch):
    options, order, cleanup, _, _ = setup(monkeypatch)
    options = replace(options, operating_system_observer=lambda *args: [])
    with pytest.raises(ValueError):
        launch(options)
    cleanup.assert_called_once()
    assert "substrate" not in order
