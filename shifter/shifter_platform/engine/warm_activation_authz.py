"""Authorization gate for the warm-pool ``activate`` operation (#28).

Extracted from :mod:`engine.launch_intents` so the launch-intent module stays
within its size budget and the warm-specific authority rule lives on its own seam.
Activation is authorized only for a *claimed* warm generation on a realized,
system-prepared (quarantined ``PROVISIONING``) range -- never for an arbitrary
range that merely happens to be ``READY``. The claimed ledger row is the authority.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.models import Range, Request


def authorize_warm_activation(request: Request, row: Range) -> None:
    """Raise ``ValueError`` unless a claimed warm generation authorizes activating ``row``.

    Two conditions must both hold: a ``CLAIMED`` warm generation exists for the
    request (the atomic claim committed), and the range is still quarantined in
    ``PROVISIONING`` (never public ``READY``) -- activation is the transition to
    ``READY``. Either failing means activation is not authorized.
    """
    from engine.models import Range, WarmRangeGeneration

    claimed = WarmRangeGeneration.objects.filter(
        request_id=request.request_id, state=WarmRangeGeneration.State.CLAIMED
    ).exists()
    if not claimed:
        raise ValueError("no claimed warm generation authorizes activation for this request")
    if row.status != Range.Status.PROVISIONING:
        raise ValueError("range state does not authorize activation")
