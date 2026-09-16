"""Canonical warm-pool compatibility digest (#28).

A warm generation may serve an initial launch only when it was prepared from the
*exact* immutable inputs that launch would otherwise provision cold. This module
computes the single canonical digest both sides compare: the reconciler stamps a
ready generation with the digest of the inputs it prepared, and the launch claim
path computes the digest of the requested launch and matches a ready generation
whose digest is equal. Digest equality is the authoritative compatibility proof;
the operator's bucket declaration only says *which* dimensions a bucket warms.

The digest is computed **after** incumbent validation and backend admission. This
module does not parse scenarios, plans, packages, or images. The immutable
realization identity is the registered RAES ``package_digest`` plus ``lock_digest``
(``cms.models.scenarios.RaesPackageSource``): per #1607 the package digest is bound
to the validated pack bytes and verified at launch, and the lock digest pins the
resolved image/content/artifact/plan set, so the pair is a complete, user-neutral
realization identity without re-compiling the plan or re-resolving images here
(no second scenario parser -- preflight #28).

The digest reuses :func:`shared.operation_envelope.canonical_payload_digest` so it
is byte-stable and key-order independent, exactly like the operation-record digest.
A change to any immutable input yields a different digest, which retires the old
ready generations through the canonical destroy lifecycle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from shared.operation_envelope import canonical_payload_digest

__all__ = [
    "CompatibilityKey",
    "WarmPoolCompatibilityError",
    "compatibility_digest",
]

#: A schema tag mixed into every digest so a future change to the set of
#: compatibility dimensions cannot silently collide with a digest minted under an
#: older dimension set. Bump when the meaning of a field changes or a field is
#: added/removed.
COMPATIBILITY_SCHEMA = "range-warm-compatibility/v1"


class WarmPoolCompatibilityError(Exception):
    """A compatibility key is missing a required immutable dimension."""


# Dimensions that must be present and non-empty: a warm generation cannot be
# proven compatible without them. The posture fields (egress/access mode) are still
# part of the digest but may be empty, because an absent posture is a distinct,
# valid compatibility value.
_REQUIRED_FIELDS = (
    "backend",
    "instantiation_purpose",
    "range_source",
    "workspace_isolation_class",
    "scenario",
    "package_digest",
    "lock_digest",
)


@dataclass(frozen=True)
class CompatibilityKey:
    """The immutable inputs that decide warm-pool compatibility for one launch.

    Every field is a value the launch independently resolves from its own immutable
    inputs -- never echoed from a bucket declaration. ``package_digest`` /
    ``lock_digest`` are the exact registered-source digests (#1607) that pin the
    realized topology, images, content, and declared participant-access channels;
    the rest are the admitted product/tenancy posture the launch resolves. Digest
    equality therefore proves a generation was realized from the same inputs the
    launch would provision cold.

    Pool-routing attributes (bucket id, capacity partition, placement region) are
    deliberately *not* in the digest: they are how the reconciler organizes the
    pool, and are enforced separately by the claim's effective-policy bucket-set
    filter (a launch may claim only from buckets the current server-side policy
    authorizes for it). Splitting "is this the right realization?" (digest) from "is
    this bucket still authorized for me?" (eligibility filter) keeps each proof
    honest and independently resolved.
    """

    # Admitted backend.
    backend: str
    # Product / tenancy posture the launch resolves.
    instantiation_purpose: str
    range_source: str
    workspace_isolation_class: str
    egress_mode: str
    # Immutable realization identity (subsumes topology/images/content/access).
    scenario: str
    package_digest: str
    lock_digest: str

    def normalized(self) -> dict[str, str]:
        """Return the validated, canonical mapping the digest is computed over."""
        raw = asdict(self)
        missing = [name for name in _REQUIRED_FIELDS if not str(raw.get(name, "")).strip()]
        if missing:
            raise WarmPoolCompatibilityError(
                f"compatibility key is missing required dimension(s): {', '.join(sorted(missing))}"
            )
        normalized: dict[str, str] = {"__schema__": COMPATIBILITY_SCHEMA}
        for name, value in raw.items():
            if value is not None and not isinstance(value, str):
                raise WarmPoolCompatibilityError(
                    f"compatibility dimension {name!r} must be a string, got {type(value).__name__}"
                )
            # Optional posture fields normalize an absent value to the empty string
            # so a present-but-empty and an absent value hash identically and a
            # caller cannot smuggle a None past the digest.
            normalized[name] = "" if value is None else value
        return normalized


def compatibility_digest(key: CompatibilityKey) -> str:
    """Return the canonical ``sha256:`` digest for a compatibility key.

    Byte-stable and key-order independent: two keys with equal dimension values
    produce the same digest regardless of construction order, and any changed
    dimension changes the digest.
    """
    return canonical_payload_digest(key.normalized())
