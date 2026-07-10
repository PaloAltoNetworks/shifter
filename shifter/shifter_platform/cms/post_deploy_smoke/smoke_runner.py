"""Orchestration helpers for post-deploy smoke tests."""

from __future__ import annotations

import os
from collections.abc import Mapping

from cms.post_deploy_smoke.variants import SmokeVariant


def build_agents_by_os(variant: SmokeVariant, env: Mapping[str, str] | None = None) -> dict[str, int]:
    """Resolve required SMOKE_* agent IDs for the selected variant."""
    env = env or os.environ
    agents: dict[str, int] = {}
    for key in variant.required_agent_keys:
        env_name = f"SMOKE_{key.upper()}_AGENT_ID"
        raw = env.get(env_name, "").strip()
        if not raw:
            msg = f"{env_name} is required for variant {variant.name}"
            raise ValueError(msg)
        agents[key] = int(raw)
    return agents


def select_probe_target(
    variant: SmokeVariant,
    *,
    attacker_uuid: str,
    windows_uuid: str | None = None,
) -> tuple[str, str]:
    """Choose the protocol and instance UUID to probe for the variant."""
    if variant.primary_protocol == "ssh":
        if not attacker_uuid:
            raise ValueError("attacker instance uuid is required for linux smoke")
        return "ssh", attacker_uuid
    if not windows_uuid:
        raise ValueError("windows instance uuid is required for windows smoke")
    return "rdp", windows_uuid
