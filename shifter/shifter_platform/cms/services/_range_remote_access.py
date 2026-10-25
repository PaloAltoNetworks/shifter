"""Launch-time OpenVPN admission for an RAES range (#2030).

Decides whether a launch requests participant OpenVPN authority (ADR-039-R10)
and until when. The deployment must opt in (``RANGE_OPENVPN_ENABLED``) and the
admitted backend must be one whose RAES adapter realizes the gateway. The credential
window ends at the range lease ceiling. Engine then mints the capability against
the range's persisted participant access, and a scenario that does not declare
exactly one participant-access target launches without VPN.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

#: Realization backends whose RAES adapter admits the shared OpenVPN pool (#2480).
#: EC2 is tracked by #2481.
_OPENVPN_BACKENDS = frozenset({"gce"})


def openvpn_deadline(backend: str | None, lease_ceiling: datetime | None) -> datetime | None:
    """Return the OpenVPN credential deadline for this launch, or ``None`` for no VPN.

    ``lease_ceiling`` is the range's ``maximum_expires_at``. A launch with no lease
    ceiling (a warm-pool generation) never requests VPN, so a system-owned range
    carries no participant access.
    """
    from django.conf import settings

    if (
        lease_ceiling is None
        or not getattr(settings, "RANGE_OPENVPN_ENABLED", False)
        or str(getattr(settings, "LOCAL_PROVISIONER", "") or "").strip()
        or backend not in _OPENVPN_BACKENDS
    ):
        return None
    return lease_ceiling
