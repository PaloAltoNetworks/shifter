"""Mission Control lease policy at the installation boundary (issue #27).

Thin installer adapter over the shared, Django-free
:class:`shared.mission_control_lease.MissionControlLeasePolicy`. Like
``installation.range_egress`` this owns the ``settings.mission_control_leases``
block -- a shared, cross-backend platform setting, not a backend-owned key -- so
the loader strips it before each closed backend settings model and validates it
here. The validated form is published to the runtime by
``installation.render.render_mission_control_lease_env``.

Lease durations are non-secret operator configuration, so validation messages are
surfaced verbatim (anchored under ``settings.mission_control_leases``) rather than
redacted the way secret-bearing settings are.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from shared.mission_control_lease import MissionControlLeasePolicy

from .errors import ConfigIssue

#: Reserved key under ``RootConfig.settings`` that carries the lease policy.
SETTINGS_KEY = "mission_control_leases"


def validate_settings_block(settings: Mapping[str, Any]) -> tuple[dict[str, Any], list[ConfigIssue]]:
    """Validate the ``mission_control_leases`` block within a ``settings`` mapping.

    Returns a ``(normalized_settings, issues)`` tuple:

    - ``normalized_settings`` is a shallow copy of the input with the block replaced
      by its canonical form (defaults applied). When the block is absent, the input is
      returned unchanged so an omitted policy renders the backward-compatible defaults.
    - ``issues`` is a list of :class:`ConfigIssue` records anchored under
      ``settings.mission_control_leases``.

    An *absent* key is an omission (defaults downstream); an *explicit null* block
    (``mission_control_leases:`` with no value) is a broken declaration, not an
    omission, and is rejected rather than silently activating defaults (ADR-011-R9).
    """
    normalized = dict(settings)
    issues: list[ConfigIssue] = []
    if SETTINGS_KEY in settings:
        raw = settings[SETTINGS_KEY]
        if raw is None:
            issues.append(
                ConfigIssue(
                    f"settings.{SETTINGS_KEY}",
                    "must not be null; omit the block entirely to use the default lease policy",
                )
            )
        elif not isinstance(raw, Mapping):
            issues.append(
                ConfigIssue(
                    f"settings.{SETTINGS_KEY}",
                    "must be a mapping of initial_days/extension_days/maximum_days/extensions_enabled; "
                    f"got {type(raw).__name__}",
                )
            )
        else:
            try:
                policy = MissionControlLeasePolicy.model_validate(dict(raw))
                normalized[SETTINGS_KEY] = policy.model_dump(mode="json")
            except ValidationError as exc:
                issues = _issues_from_pydantic_error(exc)
    return normalized, issues


def _issues_from_pydantic_error(exc: ValidationError) -> list[ConfigIssue]:
    """Convert a policy ``ValidationError`` into ``settings.mission_control_leases.*`` issues."""
    issues: list[ConfigIssue] = []
    for err in exc.errors():
        loc_parts = [str(part) for part in err["loc"]]
        path = ".".join(["settings", SETTINGS_KEY, *loc_parts]) if loc_parts else f"settings.{SETTINGS_KEY}"
        issues.append(ConfigIssue(path, err["msg"]))
    return issues
