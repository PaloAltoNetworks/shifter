"""Value-free semantic diff and field classification for CTF content refresh.

Centralized so live-policy enforcement, the applied change, the reported
result/audit categories, and a future read-only preview all share one
classifier instead of duplicating field allowlists (issue #1971).
"""

from __future__ import annotations

from ctf.content_bundle import BundleChallenge, BundleFlag
from ctf.models import CTFChallenge, CTFFlag

# Bundle-owned scalar fields safe to change on a live (ACTIVE/PAUSED) event:
# presentation and connection metadata that never touch authoritative scoring.
LIVE_SAFE_FIELDS = (
    "name",
    "description",
    "category",
    "difficulty",
    "flag_format",
    "solution",
    "order",
    "visibility",
    "target_instance_name",
    "target_port",
)
# Fields that drive authoritative submissions, attempt gates, and dynamic
# repricing. Changing these on a live event would rewrite competition history.
SCORING_FIELDS = (
    "points",
    "minimum_points",
    "decay_function",
    "decay_solve_count",
    "max_attempts",
)
ALL_MANAGED_FIELDS = LIVE_SAFE_FIELDS + SCORING_FIELDS

# Categories a live refresh must never change: they rewrite authoritative
# submissions, attempt gates, dynamic repricing, hint usage, or membership.
UNSAFE_LIVE_CATEGORIES = frozenset({"membership", "scoring", "hints", "prerequisites"})


def _presentation_differs(challenge: CTFChallenge, bundle_challenge: BundleChallenge) -> bool:
    """Return whether any bundle-owned presentation field diverges."""
    return any(getattr(challenge, name) != getattr(bundle_challenge, name) for name in LIVE_SAFE_FIELDS)


def _scoring_differs(challenge: CTFChallenge, bundle_challenge: BundleChallenge) -> bool:
    """Return whether any scoring/attempt field diverges."""
    return any(getattr(challenge, name) != getattr(bundle_challenge, name) for name in SCORING_FIELDS)


def _flag_material_matches(current: CTFFlag, wanted: BundleFlag) -> bool:
    """Return whether one flag's proof material matches the target declaration.

    Static hashes are salted, so equality is proven by verifying the target
    plaintext against the stored hash rather than comparing hashes. Regex
    patterns and HTTP validator configs are stored in the clear and compared
    directly. No proof value is logged or persisted for comparison.
    """
    if wanted.flag_type == "static":
        from ctf.services.challenge import verify_single_flag

        return verify_single_flag(current, wanted.value)
    if wanted.flag_type == "regex":
        return current.flag_hash == wanted.value
    return (current.validator_config or {}) == (wanted.validator_config or {})


def _flag_matches(current: CTFFlag, wanted: BundleFlag) -> bool:
    """Return whether one persisted flag matches one bundle flag declaration."""
    return (
        current.flag_type == wanted.flag_type
        and current.order == wanted.order
        and current.case_sensitive == wanted.case_sensitive
        and _flag_material_matches(current, wanted)
    )


def _flags_differ(challenge: CTFChallenge, bundle_challenge: BundleChallenge) -> bool:
    """Return whether the persisted flag set diverges from the bundle declaration."""
    existing = list(challenge.flags.all().order_by("order"))
    target = sorted(bundle_challenge.flags, key=lambda flag: flag.order)
    if len(existing) != len(target):
        return True
    return any(not _flag_matches(current, wanted) for current, wanted in zip(existing, target, strict=True))


def _hints_differ(challenge: CTFChallenge, bundle_challenge: BundleChallenge) -> bool:
    """Return whether persisted hints diverge from the bundle declaration."""
    existing = sorted((h.order, h.penalty, h.text) for h in challenge.hints.all())
    target = sorted((h.order, h.penalty, h.text) for h in bundle_challenge.hints)
    return existing != target


def _prerequisites_differ(challenge: CTFChallenge, bundle_challenge: BundleChallenge) -> bool:
    """Return whether persisted prerequisite edges diverge from the bundle."""
    existing = {edge.required_challenge.source_id for edge in challenge.prerequisites.all()}
    return existing != set(bundle_challenge.prerequisites)


def semantic_diff(
    existing: dict[str, CTFChallenge],
    bundle_by_id: dict[str, BundleChallenge],
) -> frozenset[str]:
    """Return the value-free set of categories that actually differ.

    One diff drives live-policy enforcement, the applied change, and the reported
    result/audit categories, so the strict audit records what really changed
    rather than a fixed superset.
    """
    categories: set[str] = set()
    if set(existing) != set(bundle_by_id):
        categories.add("membership")
    for source_id in set(existing) & set(bundle_by_id):
        row = existing[source_id]
        target = bundle_by_id[source_id]
        if _presentation_differs(row, target):
            categories.add("presentation")
        if _scoring_differs(row, target):
            categories.add("scoring")
        if _flags_differ(row, target):
            categories.add("flags")
        if _hints_differ(row, target):
            categories.add("hints")
        if _prerequisites_differ(row, target):
            categories.add("prerequisites")
    return frozenset(categories)


__all__ = [
    "ALL_MANAGED_FIELDS",
    "LIVE_SAFE_FIELDS",
    "SCORING_FIELDS",
    "UNSAFE_LIVE_CATEGORIES",
    "semantic_diff",
]
