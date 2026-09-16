"""Load an RAES package into a compiled provisioning plan and dispatch it.

This is the launch-side of the RAES-native path (#1479): it turns a registered
``package_ref`` into a concrete provisioning dispatch. It resolves the reference
to a contained pack root, selects the single direct SDL entry supported by the
current Shifter profile, loads + compiles it with ``raes``, plans it against
the Shifter provisioning-only backend, and applies the plan through an injected
dispatch ``port``.

Like ``runtime_target`` and ``manifest``, this is one of the few modules allowed
to import ``raes_*`` (ADR-031-R1 / ADR-024). It never imports ``cms`` or
``engine``: the concrete dispatch port is injected by the caller, so the engine
consumption path stays below the ``shared.raes`` boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from raes.artifact_requirements import ArtifactRequirement
from raes.scenarios import Scenario, ScenarioError, load_scenario
from raes_contracts.contracts import ArtifactRequirementAvailability

from shared.log_sanitize import safe_log_value
from shared.raes.artifact_inventory import ArtifactSupply
from shared.raes.dispatch_port import ShifterProvisioningDispatchPort
from shared.raes.participant_access import ParticipantAccessError, project_participant_access
from shared.raes.runtime_target import NODE_RESOURCE_TYPE, create_shifter_backend_target

#: Bounded cap for a rendered diagnostic string (ADR-031-R4: bounded evidence).
_DIAGNOSTIC_CAP = 240


class RaesPackageError(Exception):
    """An RAES package could not be resolved, loaded, or compiled for launch."""


@dataclass(frozen=True)
class ShifterLaunchResult:
    """Outcome of dispatching a compiled RAES package through the backend.

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
        RaesPackageError: if the reference is empty, escapes the root, or does
            not resolve to an existing directory.
    """
    if not package_ref or not package_ref.strip():
        raise RaesPackageError("package_ref is empty")
    root = package_root.resolve()
    candidate = (root / package_ref).resolve()
    if candidate != root and root not in candidate.parents:
        raise RaesPackageError("package_ref escapes the configured package root")
    if not candidate.is_dir():
        raise RaesPackageError("package_ref does not resolve to a pack directory")
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
        raise RaesPackageError("pack has no direct SDL entry")
    entries = sorted(
        path.resolve()
        for path in sdl_dir.iterdir()
        if path.name.endswith(".sdl.yaml") and path.is_file() and not path.is_symlink()
    )
    if len(entries) != 1:
        raise RaesPackageError("pack must contain exactly one direct SDL entry")
    scenario_path = entries[0]
    if scenario_path.parent != sdl_dir.resolve() or root not in scenario_path.parents:
        raise RaesPackageError("pack SDL entry escapes the pack root")
    return scenario_path


def load_pack_scenario(pack_root: Path) -> Scenario:
    """Load the single contained SDL entry through the shared RAES boundary.

    Consumers that need the upstream scenario projection use this seam rather
    than importing RAES tooling into an application layer. Canonical digest
    verification remains the caller's prerequisite.
    """
    scenario_path = resolve_pack_scenario_path(pack_root)
    try:
        return load_scenario(scenario_path)
    except (ScenarioError, OSError) as exc:
        raise RaesPackageError(f"failed to load RAES package: {safe_log_value(exc)}") from exc


def _render_diagnostic(diagnostic: object) -> str:
    """Render one backend diagnostic as a bounded, single-line string."""
    code = getattr(diagnostic, "code", "")
    address = getattr(diagnostic, "address", "")
    message = getattr(diagnostic, "message", "")
    rendered = f"{code} @ {address}: {message}".replace("\n", " ").replace("\r", " ")
    return rendered[:_DIAGNOSTIC_CAP]


def launch_raes_package(
    *,
    scenario_path: Path,
    port: ShifterProvisioningDispatchPort,
    parameters: dict[str, object] | None = None,
    artifact_supply_provider: Callable[
        [Mapping[str, ArtifactRequirement]], ArtifactSupply | Mapping[str, ArtifactRequirementAvailability]
    ]
    | None = None,
) -> ShifterLaunchResult:
    """Load, plan, and dispatch the RAES package at ``scenario_path``.

    Loads and compiles the SDL scenario, plans it against the Shifter
    provisioning-only backend, and applies the compiled plan through ``port``
    (which realizes it, e.g. by persisting the serialized plan and starting
    provisioning). Load/compile failures raise ``RaesPackageError`` with a
    bounded, sanitized message; a rejected apply is returned as
    ``ShifterLaunchResult(accepted=False, ...)`` with rendered diagnostics.
    """
    try:
        scenario = load_scenario(scenario_path)
    except (ScenarioError, OSError) as exc:
        raise RaesPackageError(f"failed to load RAES package: {safe_log_value(exc)}") from exc

    target = create_shifter_backend_target(port=port, scenario=scenario)
    from shared.raes.artifact_planning import plan_with_artifact_supply

    execution_plan, target = plan_with_artifact_supply(
        scenario, target, parameters=parameters, supply_provider=artifact_supply_provider
    )

    # #1710: lower the compiled participant-domain interactive access into the
    # bounded sidecar here -- this is the only point where Shifter holds the
    # RuntimeModel, which the provisioner protocol's apply(plan, snapshot) never
    # sees. An unrealizable policy (ambiguous across participants, dangling
    # target, omitted account, ...) is rejected before dispatch, so no range row
    # or cloud resource is ever created for it (ADR-032-R10).
    try:
        participant_access = project_participant_access(
            execution_plan.model.participant_behaviors,
            node_addresses=frozenset(
                resource.address
                for resource in execution_plan.provisioning.resources.values()
                if resource.resource_type == NODE_RESOURCE_TYPE
            ),
        )
    except ParticipantAccessError as exc:
        return ShifterLaunchResult(
            accepted=False,
            status="rejected",
            changed_addresses=(),
            diagnostics=(
                f"shifter-provisioner.participant-access-unrealizable: {safe_log_value(exc)}"[:_DIAGNOSTIC_CAP],
            ),
        )
    target.provisioner.bind_participant_access(participant_access)

    if any(diagnostic.is_error for diagnostic in execution_plan.diagnostics):
        return ShifterLaunchResult(
            accepted=False,
            status="rejected",
            diagnostics=tuple(_render_diagnostic(diagnostic) for diagnostic in execution_plan.diagnostics),
        )
    result = target.provisioner.enqueue(execution_plan.provisioning)
    return ShifterLaunchResult(
        accepted=result.accepted,
        status="accepted" if result.accepted else "rejected",
        changed_addresses=result.addresses,
        diagnostics=tuple(_render_diagnostic(diagnostic) for diagnostic in result.diagnostics),
    )
