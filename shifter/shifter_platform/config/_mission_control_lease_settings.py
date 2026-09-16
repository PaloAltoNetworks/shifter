"""Mission Control lease-policy Django settings (issue #27).

Binds the deployment-owned Mission Control lease policy at the composition root.
The policy is parsed and validated by :mod:`shared.mission_control_lease`; this
module only reads the environment and fails closed when a deployment declares a
policy it cannot express, exactly as ``config/_warm_pool_settings.py`` does for the
warm-pool policy. A malformed policy is a deployment error, so refusing to boot is
preferable to launching ranges with an unsafe or partial lease policy.

``MISSION_CONTROL_LEASE_POLICY_JSON`` is the install-time-validated policy rendered
into the runtime by ``installation.render.render_mission_control_lease_env``. It
carries only the four non-secret scalar fields; absent or empty yields the
canonical backward-compatible 30/30/365 defaults.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from shared.mission_control_lease import (
    MissionControlLeasePolicy,
    MissionControlLeasePolicyError,
    load_policy_json,
)

__all__ = [
    "MISSION_CONTROL_LEASE_POLICY",
]


def _load_policy() -> MissionControlLeasePolicy:
    """Parse the declared Mission Control lease policy, failing closed on bad config.

    ``os.environ.get`` returns ``None`` only when the variable is unset (defaults) and
    the exact string when it is set, so a present-but-blank value is rejected rather
    than collapsed into omission.
    """
    try:
        return load_policy_json(os.environ.get("MISSION_CONTROL_LEASE_POLICY_JSON"))
    except MissionControlLeasePolicyError as exc:
        raise ImproperlyConfigured(f"MISSION_CONTROL_LEASE_POLICY_JSON is invalid: {exc}") from exc


#: Effective deployment Mission Control lease policy (canonical defaults when unset).
MISSION_CONTROL_LEASE_POLICY = _load_policy()
