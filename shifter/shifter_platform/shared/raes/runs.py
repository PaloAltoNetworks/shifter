"""Realizability-model representation of parameterized RAES scenario runs (#1579).

ADR-034 makes "image-bearing" optional and requires that a *parameterized
experiment run* -- the multi-run unit over one scenario/profile -- be
representable in the catalog/realizability model. A run is a selected parameter
binding, not a second scenario definition and not a revived legacy
``cms.experiments`` runtime path.

This module is that representation. It reuses the RAES SDL parameterization
contract (``raes``): declared ``variables`` are the parameter schema and
``instantiate_scenario`` is the canonical binding validator. It introduces no
second template language, YAML preprocessor, or Shifter-owned substitution layer.

Like the other ``shared.raes`` modules it may import ``raes`` (ADR-031-R1);
callers outside ``shared.raes`` (for example ``cms.scenarios``) use this seam
instead of importing the tooling directly. Everything returned here is bounded
and body-free: parameter *declarations* (names/types/counts) and a one-way
binding identity, never per-run parameter values, SDL fragments, or secrets
(ADR-034 secret-handling; ADR-031-R4 bounded evidence).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from raes import SDLError, parse_sdl_file
from raes.instantiate import SDLInstantiationError, instantiate_scenario

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "RunBindingResult",
    "RunDescriptor",
    "RunParameter",
    "RunRepresentationError",
    "is_parameterized",
    "read_run_parameters",
    "validate_run_binding",
]

#: Cap for a single rendered diagnostic string (ADR-031-R4: bounded evidence).
_DIAGNOSTIC_CAP = 240
#: Cap for how many diagnostics are surfaced from one binding failure.
_MAX_DIAGNOSTICS = 20
#: Parse/read failures raes may raise for a malformed or unreadable document.
_SDL_READ_ERRORS = (SDLError, OSError, ValueError, TypeError)


class RunRepresentationError(Exception):
    """A pack's SDL could not be read to represent its parameterized runs.

    Carries only a bounded, non-sensitive label (the underlying error *class*),
    never raw RAES error text, which may echo SDL fragments or input values.
    """


@dataclass(frozen=True)
class RunParameter:
    """Bounded declaration projection of one RAES SDL ``variable``.

    This is the *schema* a parameterized run binds against -- never a per-run
    value. Declared defaults and the ``allowed_values`` enumeration are
    represented by presence/count only, so no author-declared value crosses the
    boundary.
    """

    name: str
    type: str
    required: bool
    has_default: bool
    allowed_value_count: int


@dataclass(frozen=True)
class RunDescriptor:
    """Bounded identity of one selected parameterized run.

    Per ADR-034 / preflight-1579 a run descriptor is
    ``scenario_id + profile + parameter binding identity + bounded metadata``.
    ``binding_identity`` is a one-way ``sha256`` over the canonical
    ``(scenario_id, profile, parameters)`` triple, so the same selection is
    identifiable across calls without the descriptor ever carrying the raw
    parameter values.
    """

    scenario_id: str
    profile: str
    binding_identity: str
    bound_parameter_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunBindingResult:
    """Outcome of validating a proposed run binding against declared variables.

    ``diagnostics`` are bounded, body-free strings safe for host exposure; they
    name offending variables but never echo the submitted parameter values.
    """

    ok: bool
    descriptor: RunDescriptor | None = None
    diagnostics: tuple[str, ...] = field(default_factory=tuple)


def _bounded(text: object) -> str:
    """Collapse whitespace and cap a diagnostic string (never leaks bodies)."""
    return " ".join(str(text).split())[:_DIAGNOSTIC_CAP]


def read_run_parameters(scenario_path: Path) -> tuple[RunParameter, ...]:
    """Return the declared run-parameter schema for a pack's SDL entry.

    An empty tuple means the scenario declares no variables (not a parameterized
    run unit). Parsing is pure (no subprocess); the returned declarations are
    bounded metadata only.

    Raises:
        RunRepresentationError: when the SDL document cannot be read or parsed.
    """
    try:
        scenario = parse_sdl_file(scenario_path)
    except _SDL_READ_ERRORS as exc:
        raise RunRepresentationError(type(exc).__name__) from exc
    variables = getattr(scenario, "variables", {}) or {}
    return tuple(
        RunParameter(
            name=name,
            type=variable.type.value,
            required=bool(variable.required),
            has_default=variable.default is not None,
            allowed_value_count=len(variable.allowed_values or ()),
        )
        for name, variable in sorted(variables.items())
    )


def is_parameterized(scenario_path: Path) -> bool:
    """Return True when the pack's SDL entry declares at least one variable."""
    return len(read_run_parameters(scenario_path)) > 0


def _binding_identity(scenario_id: str, profile: str, parameters: Mapping[str, object]) -> str:
    """Return a stable one-way identity for a run binding (no raw values leak)."""
    canonical = json.dumps(
        {"scenario_id": scenario_id, "profile": profile, "parameters": dict(parameters)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_run_binding(
    scenario_path: Path,
    parameters: Mapping[str, object] | None = None,
    *,
    scenario_id: str | None = None,
    profile: str | None = None,
) -> RunBindingResult:
    """Validate a proposed parameter binding against declared RAES variables.

    Delegates the authoritative check to ``raes.instantiate_scenario`` (which
    enforces declared/required/typed/allowed-value semantics), so there is no
    Shifter-side substitution layer. On success returns a bounded
    :class:`RunDescriptor`; on failure returns bounded, body-free diagnostics.

    Args:
        scenario_path: The pack's ``sdl/*.sdl.yaml`` entry.
        parameters: The proposed run binding (variable name -> value). ``None``
            or empty is valid for a scenario whose variables are all optional or
            defaulted.
        scenario_id: The catalog id for the descriptor; falls back to the SDL
            scenario ``name`` when omitted.
        profile: Optional delivery/audience profile selector.
    """
    binding = dict(parameters or {})
    normalized_profile = profile or ""
    scenario = None
    diagnostics: tuple[str, ...] = ()
    # Parse and instantiate under one guard. SDLInstantiationError (a subclass of
    # SDLError) is caught first so a binding failure yields its bounded per-error
    # messages, while any other read/parse error degrades to a bounded class label.
    try:
        scenario = parse_sdl_file(scenario_path)
        instantiate_scenario(scenario, binding, normalized_profile or None)
    except SDLInstantiationError as exc:
        scenario = None
        diagnostics = tuple(_bounded(error) for error in exc.errors[:_MAX_DIAGNOSTICS]) or (
            _bounded(type(exc).__name__),
        )
    except _SDL_READ_ERRORS as exc:
        scenario = None
        diagnostics = (_bounded(type(exc).__name__),)

    if scenario is None:
        return RunBindingResult(ok=False, diagnostics=diagnostics)

    resolved_id = scenario_id or getattr(scenario, "name", "") or ""
    descriptor = RunDescriptor(
        scenario_id=resolved_id,
        profile=normalized_profile,
        binding_identity=_binding_identity(resolved_id, normalized_profile, binding),
        bound_parameter_names=tuple(sorted(binding)),
    )
    return RunBindingResult(ok=True, descriptor=descriptor)
