"""The real public planner consumes verified inventory at compiled node addresses."""

from pathlib import Path

import yaml

from shared.raes.artifact_inventory import build_artifact_supply
from shared.raes.package_loader import launch_raes_package
from tests.shared.raes.test_package_loader import _RecordingPort
from tests.shared.raes.test_prepared_inventory import inventory_fixture


def test_real_launch_requires_admitted_preparation_facts_before_dispatch(tmp_path):
    requirement, owned = inventory_fixture()
    source = Path(__file__).parent / "fixtures/launchable/shifter-launch-min.sdl.yaml"
    raw = yaml.safe_load(source.read_text())
    raw["nodes"]["web"]["source"]["artifact_requirement"] = requirement.model_dump(mode="json")
    scenario = tmp_path / "private.sdl.yaml"
    scenario.write_text(yaml.safe_dump(raw))
    unavailable = _RecordingPort()
    assert not launch_raes_package(scenario_path=scenario, port=unavailable).accepted
    available = _RecordingPort()
    observed = []

    def supply(requirements):
        observed.extend(requirements)
        return build_artifact_supply(requirements, [owned])

    result = launch_raes_package(scenario_path=scenario, port=available, artifact_supply_provider=supply)
    assert result.accepted, result.diagnostics
    assert observed == ["provision.node.web"]
