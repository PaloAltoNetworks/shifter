"""Variant configuration for post-deploy range smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VariantName = Literal["linux", "windows"]


@dataclass(frozen=True)
class SmokeVariant:
    """Catalog scenario and timing configuration for one smoke variant.

    The post-deploy smoke validates the *platform* (range provisioning,
    guest connectivity, teardown), not scenario content. Each variant
    provisions a range built entirely from the base range AMIs
    (``os_type`` kali/ubuntu/windows with ``xdr_agent: false``), so it needs
    no user-provided XDR agent. XDR/agent install is scenario-specific and is
    exercised by real scenarios, never by the smoke — which is why the smoke
    carries no ``SMOKE_*_AGENT_ID`` requirement.
    """

    name: VariantName
    scenario_id: str
    primary_protocol: Literal["ssh", "rdp"]
    # SDL node name of the guest to probe. RAES-native ranges expose realized
    # instances keyed by their SDL node name (not a legacy attacker/victim role),
    # so the smoke selects its probe target by node name.
    probe_target_node: str
    provision_timeout_seconds: int
    connectivity_timeout_seconds: int


VARIANTS: dict[VariantName, SmokeVariant] = {
    "linux": SmokeVariant(
        name="linux",
        # Kali attacker + Ubuntu victim, both from base images (no agent). The
        # SDL node named ``attacker`` is probed over SSH.
        scenario_id="smoke-linux",
        primary_protocol="ssh",
        probe_target_node="attacker",
        provision_timeout_seconds=1800,
        connectivity_timeout_seconds=600,
    ),
    "windows": SmokeVariant(
        name="windows",
        # Kali attacker + Windows workstation, both from base images (no domain,
        # no agent). The SDL node named ``victim`` is probed over RDP.
        scenario_id="smoke-windows",
        primary_protocol="rdp",
        probe_target_node="victim",
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


# Per-backend scenario overrides. The AWS EC2 range backend allocates subnet
# CIDRs inside the range VPC and refuses authored addressing, so on AWS the
# 'linux' smoke resolves to the portable smoke-linux-aws pack instead of the
# GCP-authored smoke-linux. Tracked for convergence with a single portable
# scenario in the unite-variants follow-up (#2415).
_AWS_SCENARIO_OVERRIDES: dict[str, str] = {"smoke-linux": "smoke-linux-aws"}


def scenario_id_for(variant: SmokeVariant, cloud_provider: str) -> str:
    """Resolve the variant's registered scenario id for the active range backend."""
    if cloud_provider == "aws":
        return _AWS_SCENARIO_OVERRIDES.get(variant.scenario_id, variant.scenario_id)
    return variant.scenario_id
