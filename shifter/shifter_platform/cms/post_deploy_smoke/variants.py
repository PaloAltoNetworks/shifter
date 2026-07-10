"""Variant configuration for post-deploy range smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VariantName = Literal["linux", "windows"]


@dataclass(frozen=True)
class SmokeVariant:
    """Catalog scenario and timing configuration for one smoke variant."""

    name: VariantName
    scenario_id: str
    required_agent_keys: tuple[str, ...]
    primary_protocol: Literal["ssh", "rdp"]
    provision_timeout_seconds: int
    connectivity_timeout_seconds: int


VARIANTS: dict[VariantName, SmokeVariant] = {
    "linux": SmokeVariant(
        name="linux",
        # The basic scenario's victim is a `from_agent` instance, which requires
        # a user-provided agent to resolve its OS; create_range rejects the
        # launch with "requires at least one agent" otherwise. So the linux smoke
        # must supply a linux agent (SMOKE_LINUX_AGENT_ID), same as windows.
        scenario_id="basic",
        required_agent_keys=("linux",),
        primary_protocol="ssh",
        provision_timeout_seconds=1800,
        connectivity_timeout_seconds=600,
    ),
    "windows": SmokeVariant(
        name="windows",
        scenario_id="ad_attack_lab",
        required_agent_keys=("windows", "linux"),
        primary_protocol="rdp",
        provision_timeout_seconds=3600,
        connectivity_timeout_seconds=900,
    ),
}


def parse_variant(raw: str) -> SmokeVariant:
    """Parse a CLI variant name into a configured SmokeVariant."""
    key = raw.strip().lower()
    if key not in VARIANTS:
        allowed = ", ".join(sorted(VARIANTS))
        msg = f"unknown smoke variant {raw!r}; expected one of: {allowed}"
        raise ValueError(msg)
    return VARIANTS[key]
