"""Provider-neutral warm-pool shared contracts (#28).

Dependency-light, Django-free helpers shared by CMS, Engine, and the provisioner:
the canonical compatibility digest (:mod:`shared.warm_pool.compatibility`) that
decides which ready warm generation an initial launch may claim.
"""

from __future__ import annotations

from shared.warm_pool.activation_input import (
    ActivationInput,
    ActivationInputError,
    build_activation_input,
    parse_activation_input,
)
from shared.warm_pool.compatibility import (
    CompatibilityKey,
    WarmPoolCompatibilityError,
    compatibility_digest,
)
from shared.warm_pool.policy import (
    WarmPoolBucketPolicy,
    WarmPoolOverride,
    WarmPoolPolicyError,
    WarmPoolRuntimePolicy,
    load_policy_json,
    resolve_effective_policy,
)

__all__ = [
    "ActivationInput",
    "ActivationInputError",
    "CompatibilityKey",
    "WarmPoolBucketPolicy",
    "WarmPoolCompatibilityError",
    "WarmPoolOverride",
    "WarmPoolPolicyError",
    "WarmPoolRuntimePolicy",
    "build_activation_input",
    "compatibility_digest",
    "load_policy_json",
    "parse_activation_input",
    "resolve_effective_policy",
]
