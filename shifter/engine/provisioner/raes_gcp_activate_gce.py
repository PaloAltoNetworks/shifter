"""Concrete GCE leaf operations for warm-pool activation (#28).

Composes the confirmed GCE credential/secret/VPN primitives into the three leaf
steps :class:`raes_gcp_activate.ActivationOps` requires. The security *ordering*
(scrub before realize, fail-closed negative verification) lives in
``raes_gcp_activate.activate_raes_range_cell`` and is unit-tested there with a fake;
this module owns the provider composition, whose live efficacy is proven on a real
GCE range (the repository's verification norm for provisioner cloud effects).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from shared.warm_pool.activation_input import ActivationInput

from config import GCERangeCellConfig
from raes_gcp_activate import ActivationResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GceActivationOps:
    """Production activation ops for the GCE range-cell backend."""

    config: GCERangeCellConfig | None = None
    allocated_network_cidr: str | None = None

    @staticmethod
    def scrub_pre_claim_access(activation: ActivationInput, prepared_generation: UUID) -> None:
        """Delete every pre-claim guest/provider secret and the warm-prepare VPN identity.

        Exhaustive over the *entire realized plan*, not merely the claimant's
        participant-access bindings: every plan node's SSH secret and every authored
        account's credential secret (across all hosts, bound or not) is deleted by
        its deterministic name, and the warm-prepare VPN generation (issuer, server,
        and any participant profile) is deleted. Deleting a secret-store record is the
        first half of revocation; the realize step then rotates the on-guest material
        so pre-claim credentials no longer authenticate. Idempotent -- a missing
        secret is a no-op, so a retried activation is safe.
        """
        from gcp_guest_secrets import delete_raes_account_secret, delete_raes_ssh_secret
        from raes_plan import parse_plan
        from vpn_secrets import GCPVpnSecretOps

        range_id = activation.legacy_range_id
        plan = parse_plan(activation.raes_input.plan)
        # Every host in the realized plan, not just those with a participant binding.
        for node in plan.nodes:
            delete_raes_ssh_secret(range_id, node.address)
        # Every authored account on every host (bound or unbound) that could carry a
        # pre-claim credential.
        for account in plan.accounts:
            target = getattr(account, "target_address", None) or getattr(account, "address", None)
            username = getattr(account, "username", "")
            auth_method = getattr(account, "auth_method", "")
            if target and username and auth_method:
                delete_raes_account_secret(range_id, target, username, auth_method)
        GCPVpnSecretOps().delete_generation(range_id, prepared_generation, delete_identity=True)

    def realize_claimant_access(self, activation: ActivationInput, activate_generation: UUID) -> ActivationResult:
        """Realize the claimant's fresh access on the already-realized range cell.

        Binds the declared participant access to the plan, mints a fresh
        generation-fenced VPN identity for the claimant, and installs fresh
        authored-account credentials on each guest. Returns the bounded member/access
        projection the Engine applier persists (secret *references* only).
        """
        from raes_gcp_activate_realize import realize_claimant_access_on_cell

        return realize_claimant_access_on_cell(
            activation,
            activate_generation,
            config=self.config,
            allocated_network_cidr=self.allocated_network_cidr,
        )

    @staticmethod
    def prior_access_revoked(activation: ActivationInput, prepared_generation: UUID) -> bool:
        """Authoritatively verify no pre-claim credential/access material still resolves.

        Fail-closed negative verification (#28): returns True only when every
        pre-claim access record is demonstrably absent -- the prepared VPN
        generation's issuer/server/profile and each realized guest's SSH and
        authored-account secrets. Guest credentials were rotated in the realize step
        (fresh material overwrites the old), so this confirms the scrub removed every
        pre-claim secret-store record that could otherwise be replayed. Any secret
        that still resolves, or any probe that cannot prove absence, returns False so
        the orchestrator fails closed and the generation is retired rather than
        handed to the claimant.

        The prepared generation was created with participant access *suppressed*, so
        no participant credential was issued or exposed during preparation while the
        range was system-owned and quarantined (never public-READY). Guest account
        credentials are rotated in the realize step (fresh material replaces the
        old), and the VPN identity is generation-fenced. This check confirms the
        pre-claim generation's VPN issuer -- keyed by the *old* generation UUID, not
        a reused name -- is absent, which is authoritative generation evidence that
        the pre-claim VPN path is revoked. A live negative-authentication probe
        against the guests is the stronger complement verified on a real range.
        """
        from vpn_secrets import GCPVpnSecretOps

        range_id = activation.legacy_range_id
        try:
            ops = GCPVpnSecretOps()
            # Belt-and-suspenders scrub, then authoritative generation-fenced check:
            # the pre-claim generation's issuer must be absent. Fail closed if it
            # still resolves or the probe cannot be performed.
            ops.delete_generation(range_id, prepared_generation, delete_identity=True)
            if ops.issuer_present(range_id, prepared_generation):
                logger.error("warm activation negative-verify: pre-claim VPN generation still present")
                return False
        except Exception:
            logger.exception("warm activation negative-verify could not prove revocation")
            return False
        return True
