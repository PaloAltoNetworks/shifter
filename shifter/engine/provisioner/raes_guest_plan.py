"""Provider-neutral composition targets and verified participant credential outputs."""

from __future__ import annotations

from typing import Any

from raes_access import RealizedAccessBinding
from raes_plan import RaesPlan, RaesPlanAccount


class RaesGuestPlanError(RuntimeError):
    """Authored guest intent cannot be safely realized."""


def assert_management_login_separate(plan: RaesPlan, node_address: str, username: str) -> None:
    """An authored local account cannot rotate or replace the management login."""
    if any(
        account.target_address == node_address
        and account.username == username
        and account.domain_ref is None
        and account.domain_id is None
        for account in plan.accounts
    ):
        raise RaesGuestPlanError("Authored account conflicts with the image management login")


def _assert_composition_targets_resolve(raes_plan: RaesPlan) -> None:
    """Fail closed if any content/feature/account placement targets an unknown node."""
    node_addresses = {node.address for node in raes_plan.nodes}
    placements = (
        [(c.target_address, "content", c.name) for c in raes_plan.content]
        + [(a.target_address, "account", a.username) for a in raes_plan.accounts]
        + [(f.target_address, "feature", f.name) for f in raes_plan.features]
    )
    for target, kind, name in placements:
        if target not in node_addresses:
            raise RaesGuestPlanError(f"{kind} placement {name!r} targets node {target!r} not present in this plan")


def _publish_participant_access(
    output: dict[str, Any],
    access_bindings: tuple[RealizedAccessBinding, ...],
    account_secret_refs: dict[str, str],
) -> None:
    """Attach the participant credential reference for each declared channel.

    The reference is the one the account realizer already minted and verified for
    the authored account; the reserved provisioner-management SSH secret is never
    brokered. A declared channel whose account produced no verified reference is
    a failed realization, not a silently credential-less endpoint.
    """
    public_keys = output.pop("_verified_account_public_keys", {})
    if not isinstance(public_keys, dict):
        raise RaesGuestPlanError("verified account public keys must be a mapping")
    for binding in access_bindings:
        secret_ref = account_secret_refs.get(binding.account_address, "")
        if not secret_ref:
            raise RaesGuestPlanError(
                "declared participant access has no verified account credential: "
                f"{binding.target_address}/{binding.channel}"
            )
        field = "ssh_key_secret_arn" if binding.channel == "ssh" else "rdp_password_secret_arn"
        output[field] = secret_ref
        if binding.channel == "ssh" and binding.account_address in public_keys:
            output["participant_ssh_public_key"] = public_keys[binding.account_address]


def _access_by_node(
    access_bindings: tuple[RealizedAccessBinding, ...],
) -> dict[str, tuple[RealizedAccessBinding, ...]]:
    """Group joined participant access by target node address."""
    grouped: dict[str, list[RealizedAccessBinding]] = {}
    for binding in access_bindings:
        grouped.setdefault(binding.target_address, []).append(binding)
    return {address: tuple(bindings) for address, bindings in grouped.items()}


def _accounts_by_node(raes_plan: RaesPlan) -> dict[str, tuple[RaesPlanAccount, ...]]:
    """Return local-only guest accounts grouped by target node."""
    return {
        node.address: tuple(
            account
            for account in raes_plan.accounts
            if account.target_address == node.address and account.domain_ref is None and account.domain_id is None
        )
        for node in raes_plan.nodes
    }
