"""Deterministic, lazy discovery for installed verification plugins."""

from __future__ import annotations

import importlib.metadata as metadata
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol, cast

from shared.log_sanitize import safe_log_value

from .contracts import API_VERSION, ENTRY_POINT_GROUP, AdapterDeclaration, PluginDeclaration

_DISTRIBUTION_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
_ENTRY_POINT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,63}$")
_ENTRY_POINT_FIELD = "entry-point name"


class _EntryPointLoader(Protocol):
    """Minimal load capability retained for an installed entry point."""

    def load(self) -> object:
        """Load and return the referenced plugin factory."""
        ...


class PluginDiscoveryError(RuntimeError):
    """A redaction-safe discovery, selection, load, or declaration failure."""


def _metadata_value(value: object, field_name: str, pattern: re.Pattern[str]) -> str:
    """Return one bounded, log-safe metadata value."""
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise PluginDiscoveryError(f"installed entry point has invalid {field_name}")
    if safe_log_value(value, max_len=100) != value:
        raise PluginDiscoveryError(f"installed entry point has unsafe {field_name}")
    return value


def _validate_installed_metadata(distribution: object, version: object, entry_point: object) -> tuple[str, str, str]:
    """Validate the installed metadata fields copied into a report."""
    return (
        _metadata_value(distribution, "distribution", _DISTRIBUTION_RE),
        _metadata_value(version, "version", _VERSION_RE),
        _metadata_value(entry_point, _ENTRY_POINT_FIELD, _ENTRY_POINT_RE),
    )


def _normalized_distribution(value: str) -> str:
    """Return the package-name normalization used for exact selection."""
    return re.sub(r"[-_.]+", "-", value).casefold()


@dataclass(frozen=True)
class PluginSelection:
    """Exact reviewed distribution selection supplied by the operator."""

    distribution: str
    version: str
    entry_point: str

    def __post_init__(self) -> None:
        _metadata_value(self.distribution, "distribution", _DISTRIBUTION_RE)
        _metadata_value(self.version, "version", _VERSION_RE)
        _metadata_value(self.entry_point, _ENTRY_POINT_FIELD, _ENTRY_POINT_RE)


@dataclass(frozen=True)
class InstalledPlugin:
    """Load-free installed metadata for one candidate entry point."""

    distribution: str
    distribution_version: str
    entry_point: str
    _entry_point_object: _EntryPointLoader = field(repr=False, compare=False)


@dataclass(frozen=True)
class LoadedPlugin:
    """Validated declaration bound to exact installed selection metadata."""

    distribution: str
    distribution_version: str
    entry_point: str
    declaration: PluginDeclaration

    def __post_init__(self) -> None:
        _validate_installed_metadata(self.distribution, self.distribution_version, self.entry_point)
        if not isinstance(self.declaration, PluginDeclaration):
            raise TypeError("declaration must be PluginDeclaration")

    @property
    def plugin_id(self) -> str:
        return self.declaration.plugin_id

    @property
    def plugin_version(self) -> str:
        return self.declaration.plugin_version

    @property
    def adapters(self) -> tuple[AdapterDeclaration, ...]:
        return self.declaration.adapters


def _distribution_metadata(entry_point: object) -> tuple[str, str]:
    """Return validated distribution name and version for an entry point."""
    distribution = getattr(entry_point, "dist", None)
    if distribution is None:
        raise PluginDiscoveryError("installed entry point has no distribution metadata")
    raw_name = getattr(distribution, "name", None)
    if raw_name is None:
        package_metadata = getattr(distribution, "metadata", {})
        raw_name = package_metadata.get("Name")
    name = _metadata_value(raw_name, "distribution", _DISTRIBUTION_RE)
    version = _metadata_value(getattr(distribution, "version", None), "version", _VERSION_RE)
    return name, version


def discover_plugins() -> tuple[InstalledPlugin, ...]:
    """Enumerate fixed-group metadata without importing plugin code."""
    discovered: list[InstalledPlugin] = []
    for entry_point in metadata.entry_points().select(group=ENTRY_POINT_GROUP):
        if getattr(entry_point, "group", None) != ENTRY_POINT_GROUP:
            continue
        distribution, version = _distribution_metadata(entry_point)
        name = _metadata_value(getattr(entry_point, "name", None), _ENTRY_POINT_FIELD, _ENTRY_POINT_RE)
        discovered.append(InstalledPlugin(distribution, version, name, entry_point))
    discovered.sort(
        key=lambda item: (
            _normalized_distribution(item.distribution),
            item.entry_point.casefold(),
            item.distribution_version,
        )
    )
    identities = [
        (
            _normalized_distribution(item.distribution),
            item.distribution_version,
            item.entry_point.casefold(),
        )
        for item in discovered
    ]
    if len(set(identities)) != len(identities):
        raise PluginDiscoveryError("installed entry-point metadata collision")
    return tuple(discovered)


def _select_candidate(candidates: tuple[InstalledPlugin, ...], selection: PluginSelection | None) -> InstalledPlugin:
    """Select exactly one installed candidate using reviewed metadata."""
    if not candidates:
        raise PluginDiscoveryError("no installed scenario-verification plugins")
    if selection is None:
        if len(candidates) != 1:
            raise PluginDiscoveryError("installed scenario-verification plugins are ambiguous")
        return candidates[0]
    matches = [
        candidate
        for candidate in candidates
        if _normalized_distribution(candidate.distribution) == _normalized_distribution(selection.distribution)
        and candidate.distribution_version == selection.version
        and candidate.entry_point == selection.entry_point
    ]
    if not matches:
        raise PluginDiscoveryError("plugin selection did not match installed metadata")
    if len(matches) != 1:
        raise PluginDiscoveryError("plugin selection is ambiguous")
    return matches[0]


def _validate_prerequisite_graph(adapters: tuple[AdapterDeclaration, ...]) -> None:
    """Reject declarations with unknown prerequisites or dependency cycles."""
    declared = {adapter.adapter_id for adapter in adapters}
    for adapter in adapters:
        unknown = set(adapter.prerequisites) - declared
        if unknown:
            raise PluginDiscoveryError("adapter declares an unknown prerequisite")

    pending = {adapter.adapter_id: set(adapter.prerequisites) for adapter in adapters}
    while pending:
        ready = {adapter_id for adapter_id, prerequisites in pending.items() if not prerequisites}
        if not ready:
            raise PluginDiscoveryError("adapter prerequisite cycle detected")
        pending = {
            adapter_id: prerequisites - ready
            for adapter_id, prerequisites in pending.items()
            if adapter_id not in ready
        }


def _validate_declaration(value: object) -> PluginDeclaration:
    """Validate and deterministically order one plugin declaration."""
    if not isinstance(value, PluginDeclaration):
        raise PluginDiscoveryError("plugin factory must return PluginDeclaration")
    if value.api_version != API_VERSION:
        raise PluginDiscoveryError("unsupported plugin API version")
    if not value.adapters:
        raise PluginDiscoveryError("plugin declaration contains no adapters")
    adapter_ids = [adapter.adapter_id for adapter in value.adapters]
    if len(set(adapter_ids)) != len(adapter_ids):
        raise PluginDiscoveryError("plugin declaration contains a duplicate adapter identity")
    _validate_prerequisite_graph(value.adapters)
    return PluginDeclaration(
        api_version=value.api_version,
        plugin_id=value.plugin_id,
        plugin_version=value.plugin_version,
        adapters=tuple(sorted(value.adapters, key=lambda adapter: adapter.adapter_id)),
    )


def load_plugin(
    installed: Iterable[InstalledPlugin],
    selection: PluginSelection | None = None,
) -> LoadedPlugin:
    """Load only the selected zero-argument factory and validate its declaration."""
    candidates = tuple(installed)
    if not all(isinstance(candidate, InstalledPlugin) for candidate in candidates):
        raise TypeError("installed must contain InstalledPlugin values")
    candidate = _select_candidate(candidates, selection)
    identity = f"distribution={candidate.distribution} entry_point={candidate.entry_point}"
    try:
        factory = candidate._entry_point_object.load()
    except Exception as exc:
        raise PluginDiscoveryError(f"failed to load {identity}: {type(exc).__name__}") from None
    if not callable(factory):
        raise PluginDiscoveryError(f"{identity} does not expose a zero-argument factory")
    plugin_factory = cast(Callable[[], object], factory)
    try:
        declaration = plugin_factory()
    except Exception as exc:
        raise PluginDiscoveryError(f"plugin factory failed for {identity}: {type(exc).__name__}") from None
    try:
        validated = _validate_declaration(declaration)
    except PluginDiscoveryError:
        raise
    # Defensive containment for malformed declarations from out-of-tree code.
    except Exception as exc:
        raise PluginDiscoveryError(f"invalid plugin declaration for {identity}: {type(exc).__name__}") from None
    return LoadedPlugin(
        distribution=candidate.distribution,
        distribution_version=candidate.distribution_version,
        entry_point=candidate.entry_point,
        declaration=validated,
    )


__all__ = [
    "InstalledPlugin",
    "LoadedPlugin",
    "PluginDiscoveryError",
    "PluginSelection",
    "discover_plugins",
    "load_plugin",
]
