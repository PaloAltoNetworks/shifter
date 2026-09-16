"""Atomic native CTF event-content hydration and drift policy."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ctf.content_bundle import BundleChallenge, BundleFlag, CtfContentBundle
from ctf.enums import EventCapability
from ctf.exceptions import CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFContentHydrationReceipt, CTFEvent
from ctf.services.authorization import assert_event_capability
from ctf.services.content_resolution import HydrationSourceEvidence, ResolvedCtfContent


@dataclass(frozen=True)
class ContentHydrationResult:
    """Bounded result of a created or idempotent hydration."""

    receipt_id: UUID
    created: bool
    challenge_count: int
    flag_count: int
    hint_count: int
    prerequisite_count: int


def _flag_payload(flag: BundleFlag) -> dict[str, object]:
    """Translate a bundle flag into the native challenge-service payload."""
    payload: dict[str, object] = {
        "flag_type": flag.flag_type,
        "case_sensitive": flag.case_sensitive,
        "order": flag.order,
    }
    if flag.flag_type in {"static", "regex"}:
        payload["flag"] = flag.value
    else:
        payload["validator_config"] = flag.validator_config
    return payload


def _challenge_payload(challenge: BundleChallenge) -> dict[str, object]:
    """Translate a bundle challenge into the native service payload."""
    return {
        "name": challenge.name,
        "description": challenge.description,
        "category": challenge.category,
        "points": challenge.points,
        "difficulty": challenge.difficulty,
        "flag_format": challenge.flag_format,
        "solution": challenge.solution,
        "max_attempts": challenge.max_attempts,
        "minimum_points": challenge.minimum_points,
        "decay_function": challenge.decay_function,
        "decay_solve_count": challenge.decay_solve_count,
        "order": challenge.order,
        "visibility": challenge.visibility,
        "target_instance_name": challenge.target_instance_name,
        "target_port": challenge.target_port,
        "flags": [_flag_payload(flag) for flag in challenge.flags],
    }


def _expected_counts(bundle: CtfContentBundle) -> tuple[int, int, int, int]:
    """Return the expected challenge, flag, hint, and edge counts."""
    return (
        len(bundle.challenges),
        sum(len(challenge.flags) for challenge in bundle.challenges),
        sum(len(challenge.hints) for challenge in bundle.challenges),
        sum(len(challenge.prerequisites) for challenge in bundle.challenges),
    )


def _receipt_matches(
    receipt: CTFContentHydrationReceipt,
    *,
    event: CTFEvent,
    resolved: ResolvedCtfContent,
) -> bool:
    """Return whether a receipt exactly describes the resolved bundle."""
    evidence = resolved.evidence
    bundle = resolved.bundle
    counts = _expected_counts(bundle)
    return (
        receipt.state == CTFContentHydrationReceipt.State.PRISTINE
        and receipt.scenario_id == event.scenario_id == bundle.scenario_id
        and receipt.reference_contract == evidence.reference_contract
        and receipt.bundle_contract == bundle.contract
        and receipt.declared_digest == evidence.declared_digest
        and receipt.object_key_fingerprint == evidence.object_key_fingerprint
        and receipt.object_identity_fingerprint == evidence.object_identity_fingerprint
        and receipt.object_size_bytes == evidence.object_size_bytes
        and (
            receipt.challenge_count,
            receipt.flag_count,
            receipt.hint_count,
            receipt.prerequisite_count,
        )
        == counts
    )


def _content_shape_matches(event: CTFEvent, bundle: CtfContentBundle) -> bool:
    """Return whether persisted graph identifiers and counts match the bundle."""
    challenges = list(
        CTFChallenge.objects.filter(event=event)
        .prefetch_related("flags", "hints", "prerequisites")
        .order_by("source_id")
    )
    expected_ids = sorted(challenge.source_id for challenge in bundle.challenges)
    if [challenge.source_id for challenge in challenges] != expected_ids:
        return False
    challenge_count, flag_count, hint_count, prerequisite_count = _expected_counts(bundle)
    return (
        len(challenges) == challenge_count
        and sum(challenge.flags.count() for challenge in challenges) == flag_count
        and sum(challenge.hints.count() for challenge in challenges) == hint_count
        and sum(challenge.prerequisites.count() for challenge in challenges) == prerequisite_count
    )


def _existing_receipt(event: CTFEvent) -> CTFContentHydrationReceipt | None:
    """Lock and return an event's hydration receipt, if present."""
    return CTFContentHydrationReceipt.objects.select_for_update().filter(event=event).first()


def _result(receipt: CTFContentHydrationReceipt, *, created: bool) -> ContentHydrationResult:
    """Build the bounded public hydration result from a receipt."""
    return ContentHydrationResult(
        receipt_id=receipt.pk,
        created=created,
        challenge_count=receipt.challenge_count,
        flag_count=receipt.flag_count,
        hint_count=receipt.hint_count,
        prerequisite_count=receipt.prerequisite_count,
    )


def _assert_empty_event(event: CTFEvent) -> None:
    """Reject hydration over content not managed by a bundle receipt."""
    if CTFChallenge.objects.filter(event=event).exists():
        raise CTFStateError(
            "Event already contains content that was not created by this bundle.",
            code="CTF_CONTENT_FOREIGN_STATE",
        )


def _create_graph(event: CTFEvent, bundle: CtfContentBundle, *, actor_id: int) -> None:
    """Create the complete native challenge graph for one event."""
    from ctf.services.challenge import add_prerequisite, create_challenge
    from ctf.services.hint import add_hint

    created: dict[str, CTFChallenge] = {}
    for challenge in bundle.challenges:
        row = create_challenge(
            event.pk,
            _challenge_payload(challenge),
            actor_id=actor_id,
            source_id=challenge.source_id,
        )
        created[challenge.source_id] = row
        for hint in challenge.hints:
            add_hint(
                row.pk,
                {"text": hint.text, "penalty": hint.penalty, "order": hint.order},
                actor_id=actor_id,
            )
    for challenge in bundle.challenges:
        for prerequisite_id in challenge.prerequisites:
            add_prerequisite(
                created[challenge.source_id].pk,
                created[prerequisite_id].pk,
                actor_id=actor_id,
            )


def _create_receipt(
    event: CTFEvent,
    bundle: CtfContentBundle,
    evidence: HydrationSourceEvidence,
    *,
    actor_id: int,
) -> CTFContentHydrationReceipt:
    """Persist immutable source evidence and expected graph counts."""
    challenge_count, flag_count, hint_count, prerequisite_count = _expected_counts(bundle)
    return CTFContentHydrationReceipt.objects.create(
        event=event,
        scenario_id=bundle.scenario_id,
        reference_contract=evidence.reference_contract,
        bundle_contract=bundle.contract,
        declared_digest=evidence.declared_digest,
        object_key_fingerprint=evidence.object_key_fingerprint,
        object_identity_fingerprint=evidence.object_identity_fingerprint,
        object_size_bytes=evidence.object_size_bytes,
        challenge_count=challenge_count,
        flag_count=flag_count,
        hint_count=hint_count,
        prerequisite_count=prerequisite_count,
        hydrated_by_id=actor_id,
    )


def hydrate_event_ctf_content(
    event_id: UUID,
    resolved: ResolvedCtfContent,
    *,
    actor_id: int,
) -> ContentHydrationResult:
    """Create a complete native challenge graph or return an exact no-op."""
    with transaction.atomic():
        try:
            event = CTFEvent.objects.select_for_update().get(pk=event_id)
        except CTFEvent.DoesNotExist:
            raise CTFValidationError("Event not found.", code="CTF_EVENT_NOT_FOUND") from None
        assert_event_capability(actor_id, event, EventCapability.CONTENT)
        if not event.is_content_modifiable:
            raise CTFStateError(
                "Event content is not modifiable.",
                code="CTF_CONTENT_EVENT_STATE",
            )
        if event.scenario_id != resolved.bundle.scenario_id:
            raise CTFValidationError(
                "Scenario CTF content does not match the event.",
                code="CTF_CONTENT_SCENARIO_MISMATCH",
            )

        receipt = _existing_receipt(event)
        if receipt is not None:
            if not _receipt_matches(receipt, event=event, resolved=resolved) or not _content_shape_matches(
                event, resolved.bundle
            ):
                raise CTFStateError(
                    "Event content has drifted from its configured bundle.",
                    code="CTF_CONTENT_DRIFT",
                )
            from ctf.services.audit import audit_content_hydration

            audit_content_hydration(actor_id=actor_id, event=event, receipt=receipt, outcome="noop")
            return _result(receipt, created=False)

        _assert_empty_event(event)
        _create_graph(event, resolved.bundle, actor_id=actor_id)
        receipt = _create_receipt(event, resolved.bundle, resolved.evidence, actor_id=actor_id)
        from ctf.services.audit import audit_content_hydration

        audit_content_hydration(actor_id=actor_id, event=event, receipt=receipt, outcome="created")
        return _result(receipt, created=True)


def mark_content_hydration_drift(
    event_id: UUID,
    *,
    actor_id: int | None,
    reason: str,
    allow_live_repair: bool = False,
) -> bool:
    """Lock and mark managed content before the caller mutates it."""
    receipt = CTFContentHydrationReceipt.objects.select_for_update().filter(event_id=event_id).first()
    if receipt is None:
        return False
    event = CTFEvent.objects.get(pk=event_id)
    if not event.is_content_modifiable and not (allow_live_repair and event.is_live_flag_repairable):
        raise CTFStateError(
            "Event content is not modifiable.",
            code="CTF_CONTENT_EVENT_STATE",
        )
    if receipt.state == CTFContentHydrationReceipt.State.DRIFTED:
        return False
    receipt.state = CTFContentHydrationReceipt.State.DRIFTED
    receipt.drift_reason = reason[:64]
    receipt.drifted_at = timezone.now()
    receipt.save(update_fields=["state", "drift_reason", "drifted_at", "updated_at"])

    from ctf.services.audit import audit_content_hydration_drift

    audit_content_hydration_drift(actor_id=actor_id, receipt=receipt)
    return True


def assert_event_content_hydration_ready(event: CTFEvent) -> None:
    """Fail activation when configured content lacks a pristine matching receipt."""
    from django.conf import settings

    reference = settings.CTF_CONTENT_REFERENCES.get(event.scenario_id)
    with transaction.atomic():
        receipt = CTFContentHydrationReceipt.objects.select_for_update().filter(event=event).first()
        if reference is None and receipt is None:
            return
        if (
            reference is None
            or receipt is None
            or receipt.state != CTFContentHydrationReceipt.State.PRISTINE
            or receipt.scenario_id != event.scenario_id
            or receipt.declared_digest != reference.digest
        ):
            raise CTFStateError(
                "Event scenario content is not ready.",
                code="CTF_CONTENT_NOT_READY",
            )


__all__ = [
    "ContentHydrationResult",
    "assert_event_content_hydration_ready",
    "hydrate_event_ctf_content",
    "mark_content_hydration_drift",
]
