"""Orchestration helpers for post-deploy smoke tests."""

from __future__ import annotations

from collections.abc import Mapping

from cms.post_deploy_smoke.variants import SmokeVariant


def select_probe_target(variant: SmokeVariant, instances_by_node: Mapping[str, str]) -> tuple[str, str]:
    """Choose the protocol and instance UUID to probe for the variant.

    ``instances_by_node`` maps an SDL node name (``attacker``/``victim``) to its
    realized instance UUID for the provisioned range. The smoke probes exactly
    one guest per variant: the Kali attacker over SSH (linux) or the Windows
    victim over RDP (windows). Both guests come from base images, so no agent is
    involved.
    """
    node = variant.probe_target_node
    target_uuid = instances_by_node.get(node, "")
    if not target_uuid:
        msg = (
            f"{variant.name} smoke expected a '{node}' node to probe over "
            f"{variant.primary_protocol}, but the provisioned range exposed none"
        )
        raise ValueError(msg)
    return variant.primary_protocol, target_uuid
