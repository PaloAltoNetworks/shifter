"""Canonical RAES realization identities shared across the GCE backend.

Kept in its own module so the guest login the provisioner injects for its own
management reachability has exactly one definition. ``raes_gcp_plan`` sets it on
every instance plan and ``raes_access`` refuses to broker it to a participant;
duplicating the literal in either place would let the two drift and silently
reopen the participant/provisioner privilege boundary (#1710).

Constants only -- no imports from the realization modules, so both directions of
that boundary can depend on it without a cycle.
"""

from __future__ import annotations

__all__ = ["RESERVED_MANAGEMENT_LOGIN"]

#: The guest account the provisioner creates and holds the key for, used for
#: management reachability (bootstrap, composition, verification, teardown). It
#: is never a participant seat: an authored account resolving to this login is
#: rejected before any credential is installed, because installing a
#: participant-controlled credential on it would hand the range owner the
#: provisioner's own management access.
RESERVED_MANAGEMENT_LOGIN = "raes"
