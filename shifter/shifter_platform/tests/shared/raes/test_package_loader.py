"""Tests for the RAES-native package launch loader (#1479).

Exercises the real load -> plan -> apply -> dispatch flow against a minimal
in-repo SDL fixture and a recording dispatch port (no DB/cloud). This is the
launch-side oracle for the two backend-conformance fixes #1479 depends on:
the manifest declaring ``switch`` support (so networks plan) and the provisional
snapshot echoing authored realization concerns (so the runtime non-approximation
gate passes).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from shared.raes.dispatch_port import ShifterDispatchResult
from shared.raes.package_loader import (
    RaesPackageError,
    ShifterLaunchResult,
    launch_raes_package,
    resolve_pack_root,
    resolve_pack_scenario_path,
)
from shared.raes.runtime_target import RAES_PROVISIONING_PLAN_KIND

_FIXTURES = Path(__file__).parent / "fixtures" / "launchable"
_MINIMAL = "shifter-launch-min.sdl.yaml"


@dataclass
class _RecordingPort:
    """Recording dispatch port: no DB/cloud, returns an accepted result."""

    request_id: str = "req-launch-1"
    accepted: bool = True
    plans: list = field(default_factory=list)

    def realize(self, compiled_plan, participant_access=()) -> ShifterDispatchResult:
        self.plans.append(compiled_plan)
        return ShifterDispatchResult(
            request_id=self.request_id,
            accepted=self.accepted,
            status="accepted" if self.accepted else "rejected",
            range_id="rng-1" if self.accepted else None,
        )


def _pack_tree(tmp_path: Path, *, entries: int = 1) -> Path:
    root = tmp_path / "packs" / "example-pack"
    sdl_dir = root / "sdl"
    sdl_dir.mkdir(parents=True)
    for index in range(entries):
        (sdl_dir / f"scenario-{index}.sdl.yaml").write_text("name: example-pack\n", encoding="utf-8")
    return root


def test_resolve_pack_root_and_single_scenario_path(tmp_path):
    expected = _pack_tree(tmp_path)
    root = resolve_pack_root("packs/example-pack", package_root=tmp_path)
    assert root == expected.resolve()
    assert resolve_pack_scenario_path(root) == (expected / "sdl" / "scenario-0.sdl.yaml").resolve()


def test_resolve_pack_root_rejects_traversal(tmp_path):
    with pytest.raises(RaesPackageError):
        resolve_pack_root("../../../../etc", package_root=tmp_path)


def test_resolve_pack_root_rejects_missing_and_empty(tmp_path):
    with pytest.raises(RaesPackageError):
        resolve_pack_root("does-not-exist", package_root=tmp_path)
    with pytest.raises(RaesPackageError):
        resolve_pack_root("   ", package_root=tmp_path)


def test_resolve_pack_scenario_path_rejects_zero_or_multiple_entries(tmp_path):
    empty_pack = _pack_tree(tmp_path, entries=0)
    with pytest.raises(RaesPackageError):
        resolve_pack_scenario_path(empty_pack)
    other = tmp_path / "other"
    multi_scenario_pack = _pack_tree(other, entries=2)
    with pytest.raises(RaesPackageError):
        resolve_pack_scenario_path(multi_scenario_pack)


def test_resolve_pack_scenario_path_rejects_symlinked_sdl(tmp_path):
    root = _pack_tree(tmp_path)
    real_sdl = root / "real-sdl"
    (root / "sdl").rename(real_sdl)
    (root / "sdl").symlink_to(real_sdl, target_is_directory=True)
    with pytest.raises(RaesPackageError):
        resolve_pack_scenario_path(root)


def test_launch_raes_package_compiles_and_dispatches():
    port = _RecordingPort()
    result = launch_raes_package(scenario_path=_FIXTURES / _MINIMAL, port=port)
    assert isinstance(result, ShifterLaunchResult)
    assert result.accepted is True
    assert result.diagnostics == ()
    # Node + network both realized (network requires the manifest 'switch' fix).
    assert any(addr.endswith("node.web") for addr in result.changed_addresses)
    assert any("network" in addr for addr in result.changed_addresses)
    # The port received exactly one serialized RAES provisioning plan.
    assert len(port.plans) == 1
    assert port.plans[0]["kind"] == RAES_PROVISIONING_PLAN_KIND


def test_launch_raes_package_rejected_dispatch_is_not_accepted():
    result = launch_raes_package(scenario_path=_FIXTURES / _MINIMAL, port=_RecordingPort(accepted=False))
    assert result.accepted is False
    assert result.status == "rejected"


def test_launch_raes_package_bad_sdl_raises_sanitized(tmp_path):
    bad = tmp_path / "broken.sdl.yaml"
    bad.write_text("name: broken\nnodes: {web: {type: NotARealType}}\n", encoding="utf-8")
    recording_port = _RecordingPort()
    with pytest.raises(RaesPackageError):
        launch_raes_package(scenario_path=bad, port=recording_port)


@dataclass
class _AccessRecordingPort:
    """Recording port that captures the #1710 participant-access sidecar."""

    request_id: str = "req-launch-access"
    accepted: bool = True
    seen: list = field(default_factory=list)

    def realize(self, compiled_plan, participant_access=()) -> ShifterDispatchResult:
        self.seen.append(tuple(participant_access))
        return ShifterDispatchResult(
            request_id=self.request_id, accepted=True, status="accepted", range_id="rng-access"
        )


def test_launch_projects_authored_interactive_access_beside_the_plan():
    """The compiled participant declaration reaches dispatch as a bounded sidecar."""
    port = _AccessRecordingPort()
    result = launch_raes_package(scenario_path=_FIXTURES / "shifter-launch-access.sdl.yaml", port=port)

    assert result.accepted is True
    (bindings,) = port.seen
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.channel == "ssh"
    assert binding.target_address.endswith("web")
    assert binding.account_address.endswith("analyst")


def test_launch_keeps_participant_access_out_of_the_serialized_plan():
    """ADR-032-R10: participant intent rides beside the plan, never inside it."""
    port = _AccessRecordingPort()
    launch_raes_package(scenario_path=_FIXTURES / "shifter-launch-access.sdl.yaml", port=port)

    port_with_plan = _RecordingPort()
    launch_raes_package(scenario_path=_FIXTURES / "shifter-launch-access.sdl.yaml", port=port_with_plan)
    serialized = port_with_plan.plans[0]
    assert "interactive_access" not in json.dumps(serialized)


def test_launch_without_authored_access_projects_an_empty_sidecar():
    port = _AccessRecordingPort()
    launch_raes_package(scenario_path=_FIXTURES / _MINIMAL, port=port)
    assert port.seen == [()]


def test_launch_rejects_ambiguous_participant_access_before_dispatch():
    """Divergent participant policies must fail closed, never be unioned."""
    port = _AccessRecordingPort()
    result = launch_raes_package(scenario_path=_FIXTURES / "shifter-launch-access-ambiguous.sdl.yaml", port=port)

    assert result.accepted is False
    assert result.status == "rejected"
    assert any("participant-access-unrealizable" in diagnostic for diagnostic in result.diagnostics)
    # Nothing was dispatched: no range row or cloud resource exists for it.
    assert port.seen == []
