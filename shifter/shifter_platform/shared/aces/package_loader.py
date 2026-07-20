"""Load an ACES package into a compiled provisioning plan and dispatch it.

This is the launch-side of the ACES-native path (#1479): it turns a registered
``package_ref`` into a concrete provisioning dispatch. It resolves the reference
to a contained pack root, selects the single direct SDL entry supported by the
current Shifter profile, loads + compiles it with ``aces-sdl``, plans it against
the Shifter provisioning-only backend, and applies the plan through an injected
dispatch ``port``.

Like ``runtime_target`` and ``manifest``, this is one of the few modules allowed
to import ``aces_*`` (ADR-031-R1 / ADR-024). It never imports ``cms`` or
``engine``: the concrete dispatch port is injected by the caller, so the engine
consumption path stays below the ``shared.aces`` boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aces_runtime import RuntimeManager
from aces_sdl.scenarios import ScenarioError, load_scenario

from shared.aces.dispatch_port import ShifterProvisioningDispatchPort
from shared.aces.runtime_target import create_shifter_backend_target
from shared.log_sanitize import safe_log_value

#: Bounded cap for a rendered diagnostic string (ADR-031-R4: bounded evidence).
_DIAGNOSTIC_CAP = 240


class AcesPackageError(Exception):
    """An ACES package could not be resolved, loaded, or compiled for launch."""


@dataclass(frozen=True)
class ShifterLaunchResult:
    """Outcome of dispatching a compiled ACES package through the backend.

    ``accepted`` is the apply result's success (dispatch accepted and the runtime
    contract gates passed). ``diagnostics`` are bounded, single-line strings safe
    for host exposure (ADR-031-R4).
    """

    accepted: bool
    status: str
    changed_addresses: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


def resolve_pack_root(package_ref: str, *, package_root: Path) -> Path:
    """Resolve ``package_ref`` to a contained pack directory.

    ``package_ref`` is the repo-relative (or root-relative) path to the pack
    root. Resolution is containment-checked so a crafted reference cannot escape
    the configured root (defense-in-depth path traversal).

    Raises:
        AcesPackageError: if the reference is empty, escapes the root, or does
            not resolve to an existing directory.
    """
    if not package_ref or not package_ref.strip():
        raise AcesPackageError("package_ref is empty")
    root = package_root.resolve()
    candidate = (root / package_ref).resolve()
    if candidate != root and root not in candidate.parents:
        raise AcesPackageError("package_ref escapes the configured package root")
    if not candidate.is_dir():
        raise AcesPackageError("package_ref does not resolve to a pack directory")
    return candidate


def resolve_pack_scenario_path(pack_root: Path) -> Path:
    """Return the single direct ``sdl/*.sdl.yaml`` entry for a pack.

    Multi-variant selection needs an explicit contract selector. Until that seam
    exists, Shifter fails closed instead of choosing an entry by filesystem
    order. Canonical digest verification is the caller's prerequisite.
    """
    root = pack_root.resolve()
    sdl_dir = root / "sdl"
    if sdl_dir.is_symlink() or not sdl_dir.is_dir():
        raise AcesPackageError("pack has no direct SDL entry")
    entries = sorted(
        path.resolve()
        for path in sdl_dir.iterdir()
        if path.name.endswith(".sdl.yaml") and path.is_file() and not path.is_symlink()
    )
    if len(entries) != 1:
        raise AcesPackageError("pack must contain exactly one direct SDL entry")
    scenario_path = entries[0]
    if scenario_path.parent != sdl_dir.resolve() or root not in scenario_path.parents:
        raise AcesPackageError("pack SDL entry escapes the pack root")
    return scenario_path


def _render_diagnostic(diagnostic: object) -> str:
    """Render one backend diagnostic as a bounded, single-line string."""
    code = getattr(diagnostic, "code", "")
    address = getattr(diagnostic, "address", "")
    message = getattr(diagnostic, "message", "")
    rendered = f"{code} @ {address}: {message}".replace("\n", " ").replace("\r", " ")
    return rendered[:_DIAGNOSTIC_CAP]


def launch_aces_package(
    *,
    scenario_path: Path,
    port: ShifterProvisioningDispatchPort,
    parameters: dict[str, object] | None = None,
) -> ShifterLaunchResult:
    """Load, plan, and dispatch the ACES package at ``scenario_path``.

    Loads and compiles the SDL scenario, plans it against the Shifter
    provisioning-only backend, and applies the compiled plan through ``port``
    (which realizes it, e.g. by persisting the serialized plan and starting
    provisioning). Load/compile failures raise ``AcesPackageError`` with a
    bounded, sanitized message; a rejected apply is returned as
    ``ShifterLaunchResult(accepted=False, ...)`` with rendered diagnostics.
    """
    try:
        scenario = load_scenario(scenario_path)
    except (ScenarioError, OSError) as exc:
        raise AcesPackageError(f"failed to load ACES package: {safe_log_value(exc)}") from exc

    manager = RuntimeManager(create_shifter_backend_target(port=port))
    execution_plan = manager.plan(scenario, parameters=parameters)
    result = manager.apply(execution_plan)
    return ShifterLaunchResult(
        accepted=result.success,
        status="accepted" if result.success else "rejected",
        changed_addresses=tuple(result.changed_addresses),
        diagnostics=tuple(_render_diagnostic(diagnostic) for diagnostic in result.diagnostics),
    )
