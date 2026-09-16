"""An image alias or a successful bootstrap cannot prove the guest OS."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from executors.base import CommandResult
from raes_operating_system import observe_operating_systems, validate_operating_systems
from raes_plan import RaesPlan, RaesPlanNode


def _plan():
    return RaesPlan(
        raes_version="3.5.0",
        nodes=(RaesPlanNode("provision.node.web", "web", "linux", 2, ()),),
        networks=(),
    )


def _execution(stdout):
    return SimpleNamespace(
        target="private-target",
        document_name="AWS-RunShellScript",
        wait_for_ready=Mock(return_value=True),
        executor=SimpleNamespace(run_command=Mock(return_value=CommandResult(True, 0, stdout, ""))),
        close=Mock(),
    )


def test_observes_every_instance_and_returns_only_bounded_guest_identity():
    executions = [_execution('ID=ubuntu\nVERSION_ID="22.04"\n'), _execution('ID=debian\nVERSION_ID="12"\n')]
    result = observe_operating_systems(
        _plan(),
        [{"uuid": "provision.node.web#0"}, {"uuid": "provision.node.web#1"}],
        execution_builder=Mock(side_effect=executions),
    )
    assert result == [
        {"instance_key": "provision.node.web#0", "family": "linux", "distribution": "ubuntu", "version": "22.04"},
        {"instance_key": "provision.node.web#1", "family": "linux", "distribution": "debian", "version": "12"},
    ]
    assert all(execution.close.called for execution in executions)


@pytest.mark.parametrize("stdout", ["", "ID=ubuntu\n", "ID=ubuntu\nID=debian\nVERSION_ID=12\n", "x" * 4097])
def test_missing_ambiguous_or_unbounded_guest_identity_fails_closed(stdout):
    execution = _execution(stdout)
    with pytest.raises(ValueError, match="operating-system"):
        observe_operating_systems(
            _plan(),
            [{"uuid": "provision.node.web#0"}, {"uuid": "provision.node.web#1"}],
            execution_builder=Mock(return_value=execution),
        )
    assert execution.close.called


def test_missing_concrete_instance_fails_before_opening_guest_channel():
    builder = Mock()
    with pytest.raises(ValueError, match="coverage"):
        observe_operating_systems(_plan(), [{"uuid": "provision.node.web#0"}], execution_builder=builder)
    builder.assert_not_called()


def test_observed_os_mismatch_cannot_satisfy_the_authored_version():
    plan = _plan()
    plan = replace(plan, nodes=(replace(plan.nodes[0], count=1, os_distribution="ubuntu", os_version="22.04"),))
    with pytest.raises(ValueError, match="operating-system"):
        validate_operating_systems(
            plan,
            [{"instance_key": "provision.node.web#0", "family": "linux", "distribution": "ubuntu", "version": "24.04"}],
        )


@pytest.mark.parametrize(
    "product, kernel, caption, expected",
    [
        (3, "10.0.20348", "Microsoft Windows Server 2022 Datacenter", "2022"),
        (2, "10.0.17763", "Microsoft Windows Server 2019 Standard", "2019"),
        (3, "10.0.26100", "Microsoft Windows Server 2025 Datacenter", "2025"),
        (1, "10.0.26100", "Microsoft Windows 11 Pro", None),
        (3, "10.0.20348", "Microsoft Windows Server 2019 Standard", None),
    ],
)
def test_windows_identity_requires_agreeing_product_and_release(product, kernel, caption, expected):
    import json

    from raes_operating_system import _windows_identity

    output = json.dumps({"family": "windows", "product_type": product, "version": kernel, "caption": caption})
    if expected is None:
        with pytest.raises(ValueError):
            _windows_identity(output)
    else:
        assert _windows_identity(output) == {"family": "windows", "distribution": "windows-server", "version": expected}


def test_standard_linux_versions_and_namespaced_rolling_channel_keep_their_semantics():
    from raes_operating_system import _linux_identity

    assert _linux_identity("ID=ubuntu\nVERSION_ID=22.04\n")["version"] == "22.04"
    assert _linux_identity("ID=kali\nVERSION_ID=2026.3\nVERSION_CODENAME=kali-rolling\n")["version"] == "rolling"


@pytest.mark.parametrize("version, accepted", [("3.19", True), ("3.19.9", True), ("3.20.1", False)])
def test_shipped_alpine_release_accepts_its_patch_versions_only(version, accepted):
    source = (
        Path(__file__).resolve().parents[4]
        / "scenario-dev/shifter-raes-validation/sdl/shifter-raes-validation.sdl.yaml"
    )
    declared = yaml.safe_load(source.read_text())["nodes"]["web"]
    plan = _plan()
    node = replace(
        plan.nodes[0],
        count=1,
        os_family=declared["os"],
        os_distribution=declared["os_distribution"],
        os_version=declared["os_version"],
    )
    plan = replace(plan, nodes=(node,))
    observations = observe_operating_systems(
        plan,
        [{"uuid": "provision.node.web#0"}],
        execution_builder=Mock(return_value=_execution(f"ID=alpine\nVERSION_ID={version}\n")),
    )
    if accepted:
        validate_operating_systems(plan, observations)
        assert observations[0]["version"] == "3.19"
    else:
        with pytest.raises(ValueError, match="operating-system"):
            validate_operating_systems(plan, observations)


@pytest.mark.parametrize("version", ["3", "3.19-rc1", "3.19.9.extra", "03.19.9", "3.019.9"])
def test_namespaced_alpine_release_rejects_malformed_versions(version):
    from raes_operating_system import _linux_identity

    with pytest.raises(ValueError, match="operating-system"):
        _linux_identity(f"ID=alpine\nVERSION_ID={version}\n")


def test_failed_probe_closes_the_channel_and_discards_guest_diagnostic():
    execution = _execution("private guest content")
    execution.executor.run_command.return_value = CommandResult(False, 1, "", "private diagnostic")
    with pytest.raises(ValueError) as error:
        observe_operating_systems(
            _plan(),
            [{"uuid": "provision.node.web#0"}, {"uuid": "provision.node.web#1"}],
            execution_builder=Mock(return_value=execution),
        )
    assert "private" not in str(error.value)
    execution.close.assert_called_once()
