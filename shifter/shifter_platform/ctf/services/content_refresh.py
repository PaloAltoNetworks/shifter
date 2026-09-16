"""Explicit, fenced, atomic refresh of bundle-managed native CTF content.

Issue #1971. A refresh reconciles a managed event to the currently configured,
digest-pinned revision of *its own* scenario. It preserves challenge UUIDs and
every historical scoring row (submissions, hint usage, ratings), so a stale
title or flag can be corrected without tearing the event down.

This is not a second hydration schema, a scenario change, or a background sync.
The organizer supplies only the expected current digest as an optimistic
concurrency fence; the server-configured ``ResolvedCtfContent`` is the target.
See ``docs/architecture/ctf-active-content-refresh-preflight-1971.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from django.db import transaction

from ctf.content_bundle import BundleChallenge, CtfContentBundle
from ctf.enums import EventCapability, EventStatus
from ctf.exceptions import CTFStateError, CTFValidationError
from ctf.models import (
    CTFChallenge,
    CTFChallengePrerequisite,
    CTFChallengeRating,
    CTFContentHydrationReceipt,
    CTFEvent,
    CTFFlag,
    CTFHint,
    CTFHintUsage,
    CTFSubmission,
)
from ctf.services.authorization import assert_event_capability
from ctf.services.challenge import _flag_hash_for_payload
from ctf.services.content_hydration import (
    _content_shape_matches,
    _existing_receipt,
    _expected_counts,
    _receipt_matches,
)
from ctf.services.content_refresh_diff import (
    ALL_MANAGED_FIELDS,
    LIVE_SAFE_FIELDS,
    UNSAFE_LIVE_CATEGORIES,
    semantic_diff,
)
from ctf.services.content_resolution import ResolvedCtfContent

_LIVE_STATES = frozenset({EventStatus.ACTIVE, EventStatus.PAUSED})
_PRE_ACTIVATION_STATES = frozenset({EventStatus.DRAFT, EventStatus.REGISTRATION})


@dataclass(frozen=True)
class ContentRefreshResult:
    """Bounded result distinguishing created/noop/refreshed outcomes."""

    receipt_id: UUID
    outcome: str
    challenge_count: int
    flag_count: int
    hint_count: int
    prerequisite_count: int
    changed_categories: tuple[str, ...] = field(default_factory=tuple)


def _managed_challenges(event: CTFEvent) -> dict[str, CTFChallenge]:
    """Return active bundle-managed challenges for an event keyed by source id."""
    rows = (
        CTFChallenge.objects.filter(event=event)
        .exclude(source_id="")
        .prefetch_related("flags", "hints", "prerequisites__required_challenge")
    )
    return {row.source_id: row for row in rows}


def _flag_rows(bundle_challenge: BundleChallenge) -> list[CTFFlag]:
    """Build unsaved CTFFlag rows from a bundle challenge via canonical hashing."""
    rows: list[CTFFlag] = []
    for flag in bundle_challenge.flags:
        flag_data = {"flag": flag.value} if flag.flag_type in {"static", "regex"} else {}
        stored = _flag_hash_for_payload(
            flag.flag_type,
            flag_data,
            case_sensitive=flag.case_sensitive,
            validator_config=flag.validator_config,
        )
        rows.append(
            CTFFlag(
                flag_hash=stored,
                flag_type=flag.flag_type,
                case_sensitive=flag.case_sensitive,
                order=flag.order,
                validator_config=flag.validator_config,
            )
        )
    return rows


def _replace_flags(challenge: CTFChallenge, bundle_challenge: BundleChallenge) -> None:
    """Atomically replace a challenge's flag set from the bundle declaration."""
    rows = _flag_rows(bundle_challenge)
    challenge.flags.all().delete()
    for row in rows:
        row.challenge = challenge
        row.save()


def _apply_challenge_fields(
    challenge: CTFChallenge,
    bundle_challenge: BundleChallenge,
    *,
    field_names: tuple[str, ...],
) -> None:
    """Copy the named bundle-owned scalar fields onto a challenge row."""
    for name in field_names:
        setattr(challenge, name, getattr(bundle_challenge, name))
    challenge.save(update_fields=[*field_names, "updated_at"])


def _two_phase_rename(existing: dict[str, CTFChallenge], bundle_by_id: dict[str, BundleChallenge]) -> None:
    """Park changing names under a unique placeholder before final assignment.

    ``unique_active_challenge_name_per_event`` is a partial unique index checked
    per statement, so swapping two challenges' names row-by-row can transiently
    collide even when the target set is valid.
    """
    for source_id, row in existing.items():
        target = bundle_by_id.get(source_id)
        if target is not None and target.name != row.name:
            row.name = f"__refresh__{row.pk}"[:200]
            row.save(update_fields=["name", "updated_at"])


def _create_managed_challenge(
    event: CTFEvent,
    bundle_challenge: BundleChallenge,
    *,
    actor_id: int,
) -> CTFChallenge:
    """Create one managed challenge row with its flags and hints (no drift audit).

    Row-level creation is used instead of the public ``create_challenge`` mutator
    so a bundle reconcile does not emit misleading per-item drift/live-repair
    audit records; the single revision audit is written by the caller.
    """
    # Ownership is enforced once by the caller; actor_id is kept for symmetry
    # with the other reconcile helpers and future per-write attribution.
    del actor_id
    challenge = CTFChallenge(event=event, source_id=bundle_challenge.source_id)
    for name in ALL_MANAGED_FIELDS:
        setattr(challenge, name, getattr(bundle_challenge, name))
    challenge.save()
    for row in _flag_rows(bundle_challenge):
        row.challenge = challenge
        row.save()
    for hint in bundle_challenge.hints:
        CTFHint.objects.create(challenge=challenge, text=hint.text, penalty=hint.penalty, order=hint.order)
    return challenge


def _replace_hints(challenge: CTFChallenge, bundle_challenge: BundleChallenge) -> None:
    """Replace a challenge's hint catalog from the bundle declaration."""
    challenge.hints.all().delete()
    for hint in bundle_challenge.hints:
        CTFHint.objects.create(challenge=challenge, text=hint.text, penalty=hint.penalty, order=hint.order)


def _rebuild_prerequisites(managed: dict[str, CTFChallenge], bundle: CtfContentBundle) -> None:
    """Rebuild the managed prerequisite graph from the bundle declaration."""
    for challenge in managed.values():
        challenge.prerequisites.all().delete()
    for bundle_challenge in bundle.challenges:
        dependent = managed[bundle_challenge.source_id]
        for required_id in bundle_challenge.prerequisites:
            CTFChallengePrerequisite.objects.create(
                challenge=dependent,
                required_challenge=managed[required_id],
            )


def _assert_no_scoring_ledger(event: CTFEvent) -> None:
    """Refuse a structural reconcile when authoritative history already exists."""
    has_ledger = (
        CTFSubmission.objects.filter(challenge__event=event).exists()
        or CTFHintUsage.objects.filter(hint__challenge__event=event).exists()
        or CTFChallengeRating.objects.filter(challenge__event=event).exists()
    )
    if has_ledger:
        raise CTFStateError(
            "Event already has participant history; content cannot be structurally reconciled.",
            code="CTF_CONTENT_REFRESH_STATE",
        )


def _reconcile_live(event: CTFEvent, bundle: CtfContentBundle, *, actor_id: int) -> tuple[str, ...]:
    """Apply presentation/verification-only refresh to a live event.

    Rejects the whole revision atomically when the semantic diff touches any
    scoring/structure category, and reports the categories that actually changed.
    """
    del actor_id
    existing = _managed_challenges(event)
    bundle_by_id = {challenge.source_id: challenge for challenge in bundle.challenges}
    changed = semantic_diff(existing, bundle_by_id)
    unsafe = changed & UNSAFE_LIVE_CATEGORIES
    if unsafe:
        raise CTFStateError(
            "Live event refresh cannot change scoring or structure.",
            code="CTF_CONTENT_REFRESH_UNSAFE",
            details={"unsafe_categories": sorted(unsafe)},
        )
    _two_phase_rename(existing, bundle_by_id)
    for source_id, row in existing.items():
        target = bundle_by_id[source_id]
        _apply_challenge_fields(row, target, field_names=LIVE_SAFE_FIELDS)
        _replace_flags(row, target)
    return tuple(sorted(changed))


def _reconcile_full(event: CTFEvent, bundle: CtfContentBundle, *, actor_id: int) -> tuple[str, ...]:
    """Reconcile the complete managed graph on a pre-activation event.

    Computes the semantic diff before mutating so the reported categories reflect
    what actually changed rather than a fixed superset.
    """
    _assert_no_scoring_ledger(event)
    existing = _managed_challenges(event)
    bundle_by_id = {challenge.source_id: challenge for challenge in bundle.challenges}
    changed = semantic_diff(existing, bundle_by_id)

    for source_id, row in existing.items():
        if source_id not in bundle_by_id:
            row.flags.all().delete()
            row.hints.all().delete()
            row.prerequisites.all().delete()
            row.delete(soft=True)

    surviving = {sid: row for sid, row in existing.items() if sid in bundle_by_id}
    _two_phase_rename(surviving, bundle_by_id)

    managed: dict[str, CTFChallenge] = {}
    for source_id, target in bundle_by_id.items():
        current = surviving.get(source_id)
        if current is None:
            managed[source_id] = _create_managed_challenge(event, target, actor_id=actor_id)
        else:
            _apply_challenge_fields(current, target, field_names=ALL_MANAGED_FIELDS)
            _replace_flags(current, target)
            _replace_hints(current, target)
            managed[source_id] = current

    _rebuild_prerequisites(managed, bundle)
    return tuple(sorted(changed))


def _apply_target_receipt(receipt: CTFContentHydrationReceipt, resolved: ResolvedCtfContent) -> None:
    """Update the receipt to the realized target evidence and set it PRISTINE."""
    bundle = resolved.bundle
    evidence = resolved.evidence
    challenge_count, flag_count, hint_count, prerequisite_count = _expected_counts(bundle)
    receipt.reference_contract = evidence.reference_contract
    receipt.bundle_contract = bundle.contract
    receipt.declared_digest = evidence.declared_digest
    receipt.object_key_fingerprint = evidence.object_key_fingerprint
    receipt.object_identity_fingerprint = evidence.object_identity_fingerprint
    receipt.object_size_bytes = evidence.object_size_bytes
    receipt.challenge_count = challenge_count
    receipt.flag_count = flag_count
    receipt.hint_count = hint_count
    receipt.prerequisite_count = prerequisite_count
    receipt.state = CTFContentHydrationReceipt.State.PRISTINE
    receipt.drift_reason = ""
    receipt.drifted_at = None
    receipt.save(
        update_fields=[
            "reference_contract",
            "bundle_contract",
            "declared_digest",
            "object_key_fingerprint",
            "object_identity_fingerprint",
            "object_size_bytes",
            "challenge_count",
            "flag_count",
            "hint_count",
            "prerequisite_count",
            "state",
            "drift_reason",
            "drifted_at",
            "updated_at",
        ]
    )


def refresh_event_ctf_content(
    event_id: UUID,
    resolved: ResolvedCtfContent,
    *,
    actor_id: int,
    expected_current_digest: str,
) -> ContentRefreshResult:
    """Reconcile a managed event to the configured revision under an optimistic fence.

    The resolved bundle is fully validated by the caller before this runs; no
    object download or parse happens under the lock. Returns a bounded result
    whose ``outcome`` is one of ``noop`` or ``refreshed``.
    """
    with transaction.atomic():
        try:
            event = CTFEvent.objects.select_for_update().get(pk=event_id)
        except CTFEvent.DoesNotExist:
            raise CTFValidationError("Event not found.", code="CTF_EVENT_NOT_FOUND") from None
        assert_event_capability(actor_id, event, EventCapability.CONTENT)

        receipt = _existing_receipt(event)
        if receipt is None:
            raise CTFStateError(
                "Event has no managed content to refresh.",
                code="CTF_CONTENT_REFRESH_STATE",
            )
        if event.scenario_id != resolved.bundle.scenario_id or receipt.scenario_id != event.scenario_id:
            raise CTFValidationError(
                "Scenario CTF content does not match the event.",
                code="CTF_CONTENT_SCENARIO_MISMATCH",
            )
        if expected_current_digest != receipt.declared_digest:
            raise CTFStateError(
                "Event content revision has changed; reload before refreshing.",
                code="CTF_CONTENT_REFRESH_CONFLICT",
            )

        previous_digest = receipt.declared_digest
        pristine_replay = (
            receipt.state == CTFContentHydrationReceipt.State.PRISTINE
            and _receipt_matches(receipt, event=event, resolved=resolved)
            and _content_shape_matches(event, resolved.bundle)
        )
        if pristine_replay:
            from ctf.services.audit import audit_content_refresh

            audit_content_refresh(
                actor_id=actor_id,
                event=event,
                receipt=receipt,
                outcome="noop",
                previous_digest=previous_digest,
                changed_categories=(),
            )
            return _result(receipt, outcome="noop")

        try:
            status = EventStatus(event.status)
        except ValueError:
            status = None
        if status in _PRE_ACTIVATION_STATES:
            changed = _reconcile_full(event, resolved.bundle, actor_id=actor_id)
        elif status in _LIVE_STATES:
            changed = _reconcile_live(event, resolved.bundle, actor_id=actor_id)
        else:
            raise CTFStateError(
                "Event state does not permit a content refresh.",
                code="CTF_CONTENT_REFRESH_STATE",
            )

        _apply_target_receipt(receipt, resolved)
        from ctf.services.audit import audit_content_refresh

        audit_content_refresh(
            actor_id=actor_id,
            event=event,
            receipt=receipt,
            outcome="refreshed",
            previous_digest=previous_digest,
            changed_categories=changed,
        )
        return _result(receipt, outcome="refreshed", changed_categories=changed)


def _result(
    receipt: CTFContentHydrationReceipt,
    *,
    outcome: str,
    changed_categories: tuple[str, ...] = (),
) -> ContentRefreshResult:
    """Build the bounded public refresh result from a receipt."""
    return ContentRefreshResult(
        receipt_id=receipt.pk,
        outcome=outcome,
        challenge_count=receipt.challenge_count,
        flag_count=receipt.flag_count,
        hint_count=receipt.hint_count,
        prerequisite_count=receipt.prerequisite_count,
        changed_categories=changed_categories,
    )


__all__ = [
    "ContentRefreshResult",
    "refresh_event_ctf_content",
]
