"""GCE warm-pool activation: hand a claimed generation to its claimant (#28).

Activation is the security postcondition of the warm pool and is stronger than an
ownership reassignment. A warm-prepared generation is a realized, system-owned,
quarantined GCE range cell with **no** participant access. When a launch atomically
claims it, this module:

1. **scrubs** every pre-claim guest/provider/access identity on the realized range
   -- host/local passwords, SSH/RDP material, and the warm-prepare VPN generation
   identity -- so nothing minted before the claim survives the ownership boundary;
2. **realizes** the claimant's fresh access -- new account credentials, a new
   generation-fenced VPN identity/profile owned by the claimant, and the declared
   participant-access bindings -- keyed on the *activate* operation generation; and
3. **verifies** negatively that the pre-claim access no longer resolves. If the
   adapter cannot prove revocation for the realized resource mix, activation fails
   closed and the generation is retired rather than handed over (preflight #28).

The claimant identity comes only from the immutable activation operation input,
never from argv/env. The steps are expressed against an injectable
:class:`ActivationOps` port so the orchestration -- scrub-before-realize ordering,
generation fencing, and fail-closed negative verification -- is unit-tested with
fakes; the default port composes the real GCE credential/VPN primitives, whose
live efficacy is proven on a real range.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from shared.warm_pool.activation_input import ActivationInput

from config import GCERangeCellConfig

logger = logging.getLogger(__name__)


class ActivationError(Exception):
    """A warm activation could not complete its scrub / realize / verify contract."""


class ActivationOps(Protocol):
    """The GCE leaf operations warm activation composes.

    Each method is idempotent and provider-facing and receives the full immutable
    activation projection (claimant identity + ownership-neutral RAES realization).
    The default implementation wires the real GCE primitives; tests inject a fake
    to exercise the orchestration.
    """

    def scrub_pre_claim_access(self, activation: ActivationInput, prepared_generation: UUID) -> None:
        """Delete every pre-claim guest secret and the warm-prepare VPN identity."""

    def realize_claimant_access(self, activation: ActivationInput, activate_generation: UUID) -> ActivationResult:
        """Install the claimant's fresh credentials, VPN generation, and participant
        access; return the realized member/access projection."""

    def prior_access_revoked(self, activation: ActivationInput, prepared_generation: UUID) -> bool:
        """Return True iff no pre-claim VPN/credential material still resolves."""


@dataclass
class ActivationResult:
    """The realized outcome of a successful activation."""

    members: list[dict[str, Any]] = field(default_factory=list)
    completion: dict[str, Any] = field(default_factory=dict)


def activate_raes_range_cell(
    *,
    activation: ActivationInput,
    prepared_generation: UUID,
    activate_generation: UUID,
    ops: ActivationOps,
) -> ActivationResult:
    """Scrub, realize, and verify a claimed generation for its claimant.

    Ordering is load-bearing: scrub *before* realize so no window exists in which
    both the pre-claim and claimant credentials are valid, and verify *after*
    realize so a claimant who cannot be given working access is never handed a
    range whose prior access still resolves. Any step failing raises
    :class:`ActivationError`; the caller reports terminal failure and the generation
    is retired through the canonical destroy lifecycle rather than handed over.
    """
    # 1. Scrub every pre-claim identity before anything claimant-specific exists.
    ops.scrub_pre_claim_access(activation, prepared_generation)

    # 2. Realize the claimant's fresh, generation-fenced access.
    result = ops.realize_claimant_access(activation, activate_generation)

    # 3. Negative verification: prior access must no longer resolve. Fail closed.
    if not ops.prior_access_revoked(activation, prepared_generation):
        raise ActivationError(
            "warm activation could not prove the pre-claim access was revoked; refusing to hand over the generation"
        )
    return result


def default_activation_ops(
    *, config: GCERangeCellConfig | None = None, allocated_network_cidr: str | None = None
) -> ActivationOps:
    """Return the production :class:`ActivationOps` wired to real GCE primitives."""
    from raes_gcp_activate_gce import GceActivationOps

    return GceActivationOps(config=config, allocated_network_cidr=allocated_network_cidr)
