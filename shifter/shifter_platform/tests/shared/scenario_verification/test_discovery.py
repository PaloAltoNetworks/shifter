from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

import pytest

from shared.scenario_verification import (
    API_VERSION,
    ENTRY_POINT_GROUP,
    AdapterDeclaration,
    AdapterOutcome,
    AdapterStatus,
    CheckReason,
    LoadedPlugin,
    PluginDeclaration,
    PluginDiscoveryError,
    PluginSelection,
    discover_plugins,
    load_plugin,
)


def _execute(context) -> AdapterOutcome:
    del context
    return AdapterOutcome(AdapterStatus.PASS, CheckReason.VERIFIED)


def _plugin(
    *,
    plugin_id: str = "synthetic.pack",
    api_version: str = API_VERSION,
    adapter_ids: tuple[str, ...] = ("checks.alpha",),
) -> PluginDeclaration:
    return PluginDeclaration(
        api_version=api_version,
        plugin_id=plugin_id,
        plugin_version="1.0",
        adapters=tuple(
            AdapterDeclaration(adapter_id, f"Synthetic check {index}", _execute)
            for index, adapter_id in enumerate(adapter_ids)
        ),
    )


@dataclass
class _Distribution:
    name: str
    version: str

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name}


class _EntryPoint:
    def __init__(
        self,
        distribution: str,
        version: str,
        name: str,
        factory,
        *,
        group: str = ENTRY_POINT_GROUP,
    ) -> None:
        self.dist = _Distribution(distribution, version)
        self.name = name
        self.group = group
        self.value = f"{distribution}:factory"
        self._factory = factory
        self.loads = 0

    def load(self):
        self.loads += 1
        return self._factory


class _EntryPoints(tuple):
    def select(self, **parameters):
        return _EntryPoints(
            entry_point
            for entry_point in self
            if all(getattr(entry_point, key) == value for key, value in parameters.items())
        )


def test_package_import_is_stdlib_shared_only_and_has_no_startup_discovery() -> None:
    script = """
import json, sys
sys.path.insert(0, '..')
before = set(sys.modules)
import shared.scenario_verification
after = set(sys.modules) - before
print(json.dumps(sorted(name for name in after if name.startswith(('django', 'boto3', 'raes_')))))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and inline synthetic script
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == []


def test_discovery_is_metadata_only_sorted_and_fixed_group(monkeypatch) -> None:
    selected = _EntryPoint("Zeta-Tools", "1.0", "zulu", lambda: _plugin())
    first = _EntryPoint("alpha-tools", "2.0", "alpha", lambda: _plugin())
    ignored = _EntryPoint("ignored", "1.0", "other", lambda: _plugin(), group="another.group")
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((selected, ignored, first)),
    )

    installed = discover_plugins()

    assert [(item.distribution, item.entry_point) for item in installed] == [
        ("alpha-tools", "alpha"),
        ("Zeta-Tools", "zulu"),
    ]
    assert selected.loads == first.loads == ignored.loads == 0


def test_explicit_selection_loads_only_the_exact_version_pinned_entry_point(
    monkeypatch,
) -> None:
    ignored = _EntryPoint("synthetic-tools", "1.0", "other", lambda: _plugin())
    selected = _EntryPoint(
        "synthetic-tools",
        "2.0",
        "reviewed",
        lambda: _plugin(adapter_ids=("checks.zulu", "checks.alpha")),
    )
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((ignored, selected)),
    )

    loaded = load_plugin(
        discover_plugins(),
        PluginSelection("synthetic-tools", "2.0", "reviewed"),
    )

    assert selected.loads == 1
    assert ignored.loads == 0
    assert isinstance(loaded, LoadedPlugin)
    assert (loaded.distribution, loaded.distribution_version, loaded.entry_point) == (
        "synthetic-tools",
        "2.0",
        "reviewed",
    )
    assert [adapter.adapter_id for adapter in loaded.adapters] == [
        "checks.alpha",
        "checks.zulu",
    ]


def test_sole_installed_entry_point_may_be_selected_implicitly(monkeypatch) -> None:
    entry_point = _EntryPoint("synthetic-tools", "1.0", "only", lambda: _plugin())
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((entry_point,)),
    )
    assert load_plugin(discover_plugins()).plugin_id == "synthetic.pack"


def test_ambiguous_empty_and_metadata_collision_fail_closed(monkeypatch) -> None:
    one = _EntryPoint("synthetic-tools", "1.0", "one", lambda: _plugin())
    two = _EntryPoint("synthetic-tools", "1.0", "two", lambda: _plugin())
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((one, two)),
    )
    candidates = discover_plugins()
    missing_selection = PluginSelection("synthetic-tools", "9.0", "one")
    with pytest.raises(PluginDiscoveryError, match="ambiguous"):
        load_plugin(candidates)
    with pytest.raises(PluginDiscoveryError, match="did not match"):
        load_plugin(candidates, missing_selection)

    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints(()),
    )
    candidates = discover_plugins()
    with pytest.raises(PluginDiscoveryError, match="no installed"):
        load_plugin(candidates)

    duplicate = _EntryPoint("synthetic-tools", "1.0", "same", lambda: _plugin())
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((duplicate, duplicate)),
    )
    with pytest.raises(PluginDiscoveryError, match="collision"):
        discover_plugins()


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: object(), "PluginDeclaration"),
        (lambda: _plugin(api_version="99"), "API version"),
        (lambda: _plugin(adapter_ids=()), "no adapters"),
        (
            lambda: _plugin(adapter_ids=("checks.same", "checks.same")),
            "duplicate adapter",
        ),
    ],
)
def test_malformed_or_unsupported_declarations_are_rejected(monkeypatch, factory, message: str) -> None:
    entry_point = _EntryPoint("synthetic-tools", "1.0", "only", factory)
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((entry_point,)),
    )
    candidates = discover_plugins()
    with pytest.raises(PluginDiscoveryError, match=message):
        load_plugin(candidates)


def test_factory_failures_include_only_metadata_and_exception_class(monkeypatch) -> None:
    secret = "orchid-lantern"

    def factory():
        raise RuntimeError(secret)

    entry_point = _EntryPoint("synthetic-tools", "1.0", "only", factory)
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((entry_point,)),
    )
    candidates = discover_plugins()
    with pytest.raises(PluginDiscoveryError) as caught:
        load_plugin(candidates)
    message = str(caught.value)
    assert "synthetic-tools" in message
    assert "only" in message
    assert "RuntimeError" in message
    assert secret not in message


def test_unknown_prerequisites_and_cycles_are_rejected(monkeypatch) -> None:
    def unknown_factory() -> PluginDeclaration:
        return PluginDeclaration(
            API_VERSION,
            "synthetic.pack",
            "1.0",
            (AdapterDeclaration("checks.alpha", "Synthetic", _execute, ("checks.missing",)),),
        )

    entry_point = _EntryPoint("synthetic-tools", "1.0", "only", unknown_factory)
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((entry_point,)),
    )
    candidates = discover_plugins()
    with pytest.raises(PluginDiscoveryError, match="unknown prerequisite"):
        load_plugin(candidates)

    def cycle_factory() -> PluginDeclaration:
        return PluginDeclaration(
            API_VERSION,
            "synthetic.pack",
            "1.0",
            (
                AdapterDeclaration("checks.alpha", "Synthetic A", _execute, ("checks.beta",)),
                AdapterDeclaration("checks.beta", "Synthetic B", _execute, ("checks.alpha",)),
            ),
        )

    entry_point = _EntryPoint("synthetic-tools", "1.0", "only", cycle_factory)
    monkeypatch.setattr(
        "shared.scenario_verification.discovery.metadata.entry_points",
        lambda: _EntryPoints((entry_point,)),
    )
    candidates = discover_plugins()
    with pytest.raises(PluginDiscoveryError, match="cycle"):
        load_plugin(candidates)
