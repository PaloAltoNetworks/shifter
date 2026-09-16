"""Warm-pool Django settings (#28).

Binds the deployment-owned warm-pool policy at the composition root. The policy
itself is parsed and validated by ``shared.warm_pool.policy``; this module only
reads the environment and fails closed when a deployment declares a policy it
cannot express, exactly as ``config/_capacity_planning_settings.py`` does for the
capacity catalog. A malformed policy is a deployment error, so refusing to boot is
preferable to silently warming against a partial or unsafe policy.

The projection carried in ``WARM_POOL_POLICY_JSON`` is the install-time-validated
output of ``installation.warm_pool.WarmPoolPolicy.runtime_projection`` rendered
into the runtime environment. It carries no secrets, provider identity, or command
material (preflight #28), only the validated policy the portal claim path and the
warm reconciler evaluate.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from shared.warm_pool.policy import WarmPoolPolicyError, WarmPoolRuntimePolicy, load_policy_json

__all__ = [
    "WARM_POOL_DEPLOYMENT_NAME",
    "WARM_POOL_METRICS_NAMESPACE",
    "WARM_POOL_POLICY",
]

#: Deployment identity used to derive the per-bucket capacity scope key so two
#: deployments never share a warm capacity budget. Defaults to the empty string,
#: which still yields a stable (if unnamed) scope.
WARM_POOL_DEPLOYMENT_NAME = os.environ.get("WARM_POOL_DEPLOYMENT_NAME", "").strip()

#: Own CloudWatch / Cloud Monitoring namespace, distinct from the capacity-planning
#: and portal-capacity namespaces so the three series stay readable (#28).
WARM_POOL_METRICS_NAMESPACE = os.environ.get("WARM_POOL_METRICS_NAMESPACE", "Shifter/WarmPool").strip()


def _load_policy() -> WarmPoolRuntimePolicy:
    """Parse the declared warm-pool policy, failing closed on malformed config."""
    try:
        return load_policy_json(os.environ.get("WARM_POOL_POLICY_JSON", ""))
    except WarmPoolPolicyError as exc:
        raise ImproperlyConfigured(f"WARM_POOL_POLICY_JSON is invalid: {exc}") from exc


#: The deployment warm-pool policy. Disabled by default (empty projection).
WARM_POOL_POLICY = _load_policy()
