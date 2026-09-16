"""Provisioner-side realized placement read-back (#2029).

Placement is chosen once at range creation (platform side) and stored on the range
row as ``placement_zone``. The provisioner is a pure reader: it binds the range
config to the stored zone and never recomputes from the ``RANGE_NETWORK_ZONES``
pool, so create and destroy target the exact same zone even if the pool later
changes. An empty stored zone means single-zone (scalar) placement and the config
is left untouched. Selection itself is tested platform-side in
``tests/engine/services/test_range_placement.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import GCERangeCellConfig
from range_placement import resolve_placement_from_range_data


@pytest.fixture
def base_config() -> GCERangeCellConfig:
    return GCERangeCellConfig(
        project_id="proj",
        region="us-central1",
        zone="us-central1-a",
        network_mode="shared-vpc",
        network_id="projects/proj/global/networks/range",
    )


class _CapturedConfig(Exception):
    """Sentinel raised by a plan-render stub after it captures the bound config."""

    def __init__(self, config: GCERangeCellConfig) -> None:
        super().__init__("captured")
        self.config = config


# --------------------------------------------------------------------------- #
# Reader                                                                       #
# --------------------------------------------------------------------------- #


def test_stored_zone_binds_zone_and_derives_region(base_config):
    range_data = {"subnet_index": 2, "placement_zone": "us-east4-a"}
    resolved = resolve_placement_from_range_data(base_config, range_data)
    assert (resolved.zone, resolved.region) == ("us-east4-a", "us-east4")


def test_empty_placement_leaves_the_scalar_config_untouched(base_config):
    """A single-zone / pre-#2029 range has no stored zone and must not be re-homed."""
    range_data = {"subnet_index": 2, "placement_zone": ""}
    assert resolve_placement_from_range_data(base_config, range_data) is base_config


def test_missing_placement_key_leaves_the_scalar_config_untouched(base_config):
    """A legacy row that predates the column resolves to no placement, not an error."""
    assert resolve_placement_from_range_data(base_config, {"subnet_index": 2}) is base_config


# --------------------------------------------------------------------------- #
# Legacy lifecycle wiring: the stored zone reaches plan rendering              #
# --------------------------------------------------------------------------- #


def test_legacy_apply_renders_the_stored_zone(monkeypatch, base_config):
    import gcp_range_cells as apply_mod

    monkeypatch.setattr(
        apply_mod, "get_range_data_by_request_id", lambda _r: {"subnet_index": 2, "placement_zone": "us-east4-a"}
    )

    def _capture(_request_uuid, _variables, config, **_kwargs):
        raise _CapturedConfig(config)

    monkeypatch.setattr(apply_mod, "render_range_cell_plan", _capture)

    with pytest.raises(_CapturedConfig) as caught:
        apply_mod.apply_range_cell("req-1", {"some": "var"}, config=base_config)

    assert (caught.value.config.zone, caught.value.config.region) == ("us-east4-a", "us-east4")


def test_legacy_destroy_renders_the_same_stored_zone(monkeypatch, base_config):
    import gcp_range_cell_destroy as destroy_mod

    monkeypatch.setattr(
        destroy_mod, "get_range_data_by_request_id", lambda _r: {"subnet_index": 2, "placement_zone": "us-east4-a"}
    )

    def _capture(_request_uuid, _variables, config, **_kwargs):
        raise _CapturedConfig(config)

    monkeypatch.setattr(destroy_mod, "render_range_cell_plan", _capture)

    with pytest.raises(_CapturedConfig) as caught:
        destroy_mod.destroy_range_cell("req-1", {"some": "var"}, config=base_config)

    # Destroy reconstructs the exact zone stored at creation, regardless of any
    # later pool edits.
    assert (caught.value.config.zone, caught.value.config.region) == ("us-east4-a", "us-east4")


def test_legacy_destroy_of_a_pre_migration_row_keeps_the_scalar_zone(monkeypatch, base_config):
    import gcp_range_cell_destroy as destroy_mod

    monkeypatch.setattr(
        destroy_mod, "get_range_data_by_request_id", lambda _r: {"subnet_index": 2, "placement_zone": ""}
    )

    def _capture(_request_uuid, _variables, config, **_kwargs):
        raise _CapturedConfig(config)

    monkeypatch.setattr(destroy_mod, "render_range_cell_plan", _capture)

    with pytest.raises(_CapturedConfig) as caught:
        destroy_mod.destroy_range_cell("req-1", {"some": "var"}, config=base_config)

    assert (caught.value.config.zone, caught.value.config.region) == ("us-central1-a", "us-central1")
