"""Independent apply-time realization evidence for ACES composition features.

This module is the *evidence* half of the realizability ledger, deliberately kept
separate from the *declaration* half (``shared.aces.manifest``'s
``ProvisionerCapabilities``). The manifest declares what a plan may author at plan
time; this policy records which account features the Shifter backend genuinely
realizes as a guest effect. ``shared.aces.composition_envelope`` consults it on the
one pure ``validate()`` / ``apply()`` path so a plan requesting a declared-but-not-
realized account feature fails closed before dispatch.

The two envelopes must agree in production but are **independently variable**: this
set is hand-authored and is never derived from the manifest. That independence is
the point -- if a future change re-declares a capability in the manifest without a
matching entry here (and the cross-boundary realization evidence behind it), the
apply-time gate still rejects it, so the manifest cannot silently over-claim again.

This is a bounded compatibility shim, not a replacement for the upstream ACES
non-approximation gate (``aces_processor.semantics.realization.CONCERN_PAYLOAD_PATH``),
which covers node-type / os-family / content-type but has no account-feature concern
in the pinned aces-sdl release. Remove the shim in favour of the public gate once a
released ACES contract exposes account-feature realization evidence.

A sibling issue adds a term here (and to the manifest) only after the provisioner
genuinely realizes it with cross-boundary proof: ``auth_method`` -> #1560 and
``spn`` -> #1561. The set is intentionally not an OS dispatch table; applicability
that is narrower than the backend's full OS envelope must be enforced by a public
topology/profile binding and the independent admission policy.
"""

from __future__ import annotations

#: Account-feature terms the Shifter backend genuinely realizes as a guest effect,
#: independent of ``ProvisionerCapabilities.supported_account_features``. Hand-authored
#: evidence, never auto-derived from the manifest declaration.
REALIZED_ACCOUNT_FEATURES: frozenset[str] = frozenset({"groups", "shell", "home", "disabled", "auth_method", "spn"})

#: Feature-binding shapes with an implemented, independently verified guest
#: effect (#1565). This is intentionally not derived from the public manifest:
#: the common validate/apply path must continue to reject a manifest over-claim.
REALIZED_FEATURE_TYPES: frozenset[str] = frozenset({"service", "artifact", "configuration"})

__all__ = ["REALIZED_ACCOUNT_FEATURES", "REALIZED_FEATURE_TYPES"]
