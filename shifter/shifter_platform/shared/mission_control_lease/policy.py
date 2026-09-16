"""Provider-neutral Mission Control range-lease policy (issue #27).

One immutable typed contract shared by the installation package (install-time
validation of ``settings.mission_control_leases`` in ``shifter.yaml``) and Django
settings (runtime binding from ``MISSION_CONTROL_LEASE_POLICY_JSON``). It is
deliberately Django-free and provider-neutral so both the independently packaged
installer and the platform runtime consume the *same* type -- no duplicated
model, no per-provider arithmetic (ADR-011-R9).

Durations are whole elapsed 24-hour periods. ``extensions_enabled`` is a live
deployment admission switch, distinct from the three per-generation durations:
turning it off denies further extensions without shortening deadlines or
disabling automatic cleanup.
"""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError, model_validator

__all__ = [
    "DEFAULT_EXTENSIONS_ENABLED",
    "DEFAULT_EXTENSION_DAYS",
    "DEFAULT_INITIAL_DAYS",
    "DEFAULT_MAXIMUM_DAYS",
    "MAX_LEASE_DAYS",
    "MissionControlLeasePolicy",
    "MissionControlLeasePolicyError",
    "dump_policy_json",
    "load_policy_json",
]

DEFAULT_INITIAL_DAYS = 30
DEFAULT_EXTENSION_DAYS = 30
DEFAULT_MAXIMUM_DAYS = 365
DEFAULT_EXTENSIONS_ENABLED = True

# Upper bound on any single duration: generous (100 years) but finite, so a
# fat-fingered value cannot overflow ``timedelta``/``datetime`` arithmetic or a
# credential ``notAfter`` encoder when a deadline is computed at launch.
MAX_LEASE_DAYS = 36500

# ``StrictInt`` rejects bools, floats, and numeric strings; combined with the
# bounds this fails fast on nonpositive, fractional, string, and overflow-prone
# durations rather than silently coercing them.
_LeaseDays = Annotated[StrictInt, Field(gt=0, le=MAX_LEASE_DAYS)]


class MissionControlLeasePolicyError(Exception):
    """The Mission Control lease policy JSON is missing, malformed, or invalid."""


class MissionControlLeasePolicy(BaseModel):
    """Operator-declared Mission Control lease policy (provider-neutral)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_days: _LeaseDays = DEFAULT_INITIAL_DAYS
    extension_days: _LeaseDays = DEFAULT_EXTENSION_DAYS
    maximum_days: _LeaseDays = DEFAULT_MAXIMUM_DAYS
    extensions_enabled: StrictBool = DEFAULT_EXTENSIONS_ENABLED

    @model_validator(mode="after")
    def _check_bounds(self) -> MissionControlLeasePolicy:
        # ``initial_days == maximum_days`` is valid (a fixed, non-extendable lease).
        # ``extension_days`` may exceed ``maximum_days``: an extension is bounded by
        # the generation's remaining lifetime at extension time, not by a product
        # ceiling, so a large increment simply saturates at the persisted maximum.
        if self.initial_days > self.maximum_days:
            raise ValueError(f"initial_days ({self.initial_days}) must not exceed maximum_days ({self.maximum_days})")
        return self


def load_policy_json(raw: str | None) -> MissionControlLeasePolicy:
    """Parse the policy JSON delivered at runtime, failing closed on bad input.

    Only true absence (``raw is None`` -- the variable is unset) yields the canonical
    backward-compatible defaults. A *present* but blank value is a broken deployment
    substitution, not an omission, so it is rejected rather than silently activating
    30/30/365 (ADR-011-R9). Callers must pass ``None`` only when the variable is unset
    and the exact string otherwise, so this boundary can tell the two apart.
    """
    if raw is None:
        return MissionControlLeasePolicy()
    text = raw.strip()
    if not text:
        raise MissionControlLeasePolicyError(
            "Mission Control lease policy is present but blank; unset the variable to use the defaults"
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MissionControlLeasePolicyError(f"Mission Control lease policy is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MissionControlLeasePolicyError("Mission Control lease policy must be a JSON object")
    try:
        return MissionControlLeasePolicy.model_validate(data)
    except ValidationError as exc:
        raise MissionControlLeasePolicyError(f"Mission Control lease policy is invalid: {exc}") from exc


def dump_policy_json(policy: MissionControlLeasePolicy) -> str:
    """Serialize the policy to compact canonical JSON for env delivery."""
    return policy.model_dump_json()
