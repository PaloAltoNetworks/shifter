"""In-place managed CTF content refresh: reconcile, fence, and policy (issue #1971)."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.content_bundle import parse_ctf_content_bundle
from ctf.enums import EventStatus
from ctf.exceptions import CTFPermissionError, CTFStateError
from ctf.models import CTFChallenge, CTFContentHydrationReceipt, CTFEvent, CTFFlag
from ctf.services.challenge import verify_single_flag
from ctf.services.content_hydration import hydrate_event_ctf_content
from ctf.services.content_refresh import refresh_event_ctf_content
from ctf.services.content_resolution import HydrationSourceEvidence, ResolvedCtfContent

_DIGEST_A = f"sha256:{'a' * 64}"
_DIGEST_B = f"sha256:{'b' * 64}"


def _bundle(
    *,
    one_name: str = "Challenge One",
    one_flag: str = "TEST{one}",
    one_points: int = 100,
    include_two: bool = True,
    include_three: bool = False,
):
    challenges = [
        {
            "id": "challenge-one",
            "name": one_name,
            "description": "Inspect the portal.",
            "category": "Module 1",
            "points": one_points,
            "difficulty": "easy",
            "order": 1,
            "flags": [{"type": "static", "value": one_flag, "order": 0}],
            "hints": [{"text": "Start with the portal.", "penalty": 0, "order": 1}],
            "prerequisites": [],
        }
    ]
    if include_two:
        challenges.append(
            {
                "id": "challenge-two",
                "name": "Challenge Two",
                "description": "Follow the evidence.",
                "category": "Module 1",
                "points": 200,
                "difficulty": "medium",
                "order": 2,
                "flags": [{"type": "regex", "value": "^TEST\\{two-[0-9]+\\}$", "order": 0}],
                "hints": [],
                "prerequisites": ["challenge-one"],
            }
        )
    if include_three:
        challenges.append(
            {
                "id": "challenge-three",
                "name": "Challenge Three",
                "description": "Pivot deeper.",
                "category": "Module 2",
                "points": 300,
                "difficulty": "hard",
                "order": 3,
                "flags": [{"type": "static", "value": "TEST{three}", "order": 0}],
                "hints": [],
                "prerequisites": ["challenge-one"],
            }
        )
    raw = json.dumps(
        {"contract": "shifter-ctf-content/v1", "scenario_id": "scenario-one", "challenges": challenges}
    ).encode()
    return parse_ctf_content_bundle(raw)


def _resolved(bundle, digest: str = _DIGEST_A) -> ResolvedCtfContent:
    return ResolvedCtfContent(
        bundle=bundle,
        evidence=HydrationSourceEvidence(
            reference_contract="shifter-ctf-content-references/v1",
            declared_digest=digest,
            object_key_fingerprint="b" * 64,
            object_identity_fingerprint="c" * 64,
            object_size_bytes=1024,
        ),
    )


def _event(organizer_user, *, status: str = EventStatus.DRAFT.value) -> CTFEvent:
    now = timezone.now()
    return CTFEvent.objects.create(
        name="Refresh Test",
        created_by=organizer_user,
        status=status,
        event_start=now + timedelta(hours=1),
        event_end=now + timedelta(hours=2),
        scenario_id="scenario-one",
    )


def _hydrate_then_set(organizer_user, *, status: str) -> CTFEvent:
    """Hydrate content in DRAFT (content-modifiable), then move to a target state."""
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(_bundle(), _DIGEST_A), actor_id=organizer_user.pk)
    if status != EventStatus.DRAFT.value:
        event.status = status
        event.save(update_fields=["status", "updated_at"])
    return event


@pytest.mark.django_db
def test_live_refresh_replaces_stale_title_and_flag_on_same_uuid(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    original = CTFChallenge.objects.get(event=event, source_id="challenge-one")

    result = refresh_event_ctf_content(
        event.pk,
        _resolved(_bundle(one_name="Fixed Name", one_flag="TEST{one-fixed}"), _DIGEST_B),
        actor_id=organizer_user.pk,
        expected_current_digest=_DIGEST_A,
    )

    refreshed = CTFChallenge.objects.get(event=event, source_id="challenge-one")
    assert result.outcome == "refreshed"
    assert refreshed.pk == original.pk  # UUID preserved -> submissions stay attached
    assert refreshed.name == "Fixed Name"
    flag = CTFFlag.objects.get(challenge=refreshed)
    assert verify_single_flag(flag, "TEST{one-fixed}") is True  # new proof accepted
    assert verify_single_flag(flag, "TEST{one}") is False  # old proof rejected
    receipt = CTFContentHydrationReceipt.objects.get(event=event)
    assert receipt.state == CTFContentHydrationReceipt.State.PRISTINE
    assert receipt.declared_digest == _DIGEST_B


@pytest.mark.django_db
def test_live_refresh_reports_only_the_flags_category(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    result = refresh_event_ctf_content(
        event.pk,
        _resolved(_bundle(one_flag="TEST{one-new}"), _DIGEST_B),
        actor_id=organizer_user.pk,
        expected_current_digest=_DIGEST_A,
    )
    # Only the flag changed; the audit/result must not claim presentation changed.
    assert result.changed_categories == ("flags",)


@pytest.mark.django_db
def test_draft_refresh_reports_only_actual_changed_categories(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(_bundle(), _DIGEST_A), actor_id=organizer_user.pk)
    result = refresh_event_ctf_content(
        event.pk,
        _resolved(_bundle(one_name="Only Retitled"), _DIGEST_B),
        actor_id=organizer_user.pk,
        expected_current_digest=_DIGEST_A,
    )
    # A title-only draft revision must not report membership/scoring/flags.
    assert result.changed_categories == ("presentation",)


@pytest.mark.django_db
def test_exact_pristine_replay_is_noop(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    result = refresh_event_ctf_content(
        event.pk,
        _resolved(_bundle(), _DIGEST_A),
        actor_id=organizer_user.pk,
        expected_current_digest=_DIGEST_A,
    )
    assert result.outcome == "noop"


@pytest.mark.django_db
def test_refresh_restores_drifted_managed_content(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    from ctf.services.content_hydration import mark_content_hydration_drift

    mark_content_hydration_drift(event.pk, actor_id=organizer_user.pk, reason="manual_edit", allow_live_repair=True)
    assert CTFContentHydrationReceipt.objects.get(event=event).state == CTFContentHydrationReceipt.State.DRIFTED

    result = refresh_event_ctf_content(
        event.pk,
        _resolved(_bundle(), _DIGEST_A),  # unchanged digest, drift restore
        actor_id=organizer_user.pk,
        expected_current_digest=_DIGEST_A,
    )
    assert result.outcome == "refreshed"
    assert CTFContentHydrationReceipt.objects.get(event=event).state == CTFContentHydrationReceipt.State.PRISTINE


@pytest.mark.django_db
def test_live_refresh_rejects_scoring_change_atomically(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    resolved = _resolved(_bundle(one_name="Should Not Apply", one_points=999), _DIGEST_B)
    with pytest.raises(CTFStateError) as error:
        refresh_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk, expected_current_digest=_DIGEST_A)
    assert error.value.code == "CTF_CONTENT_REFRESH_UNSAFE"
    # Atomic rollback: neither the name nor the digest changed.
    assert CTFChallenge.objects.get(event=event, source_id="challenge-one").name == "Challenge One"
    assert CTFContentHydrationReceipt.objects.get(event=event).declared_digest == _DIGEST_A


@pytest.mark.django_db
def test_live_refresh_rejects_membership_change(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    resolved = _resolved(_bundle(include_two=False), _DIGEST_B)
    with pytest.raises(CTFStateError) as error:
        refresh_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk, expected_current_digest=_DIGEST_A)
    assert error.value.code == "CTF_CONTENT_REFRESH_UNSAFE"


@pytest.mark.django_db
def test_stale_expected_digest_is_a_conflict(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    resolved = _resolved(_bundle(one_flag="TEST{x}"), _DIGEST_B)
    with pytest.raises(CTFStateError) as error:
        # expected_current_digest is not the current receipt digest
        refresh_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk, expected_current_digest=_DIGEST_B)
    assert error.value.code == "CTF_CONTENT_REFRESH_CONFLICT"


@pytest.mark.django_db
def test_unmanaged_event_cannot_refresh(organizer_user) -> None:
    event = _event(organizer_user)  # no hydration receipt
    resolved = _resolved(_bundle(), _DIGEST_A)
    with pytest.raises(CTFStateError) as error:
        refresh_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk, expected_current_digest=_DIGEST_A)
    assert error.value.code == "CTF_CONTENT_REFRESH_STATE"


@pytest.mark.django_db
def test_ended_event_is_not_refreshable(organizer_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ENDED.value)
    resolved = _resolved(_bundle(one_flag="TEST{x}"), _DIGEST_B)
    with pytest.raises(CTFStateError) as error:
        refresh_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk, expected_current_digest=_DIGEST_A)
    assert error.value.code == "CTF_CONTENT_REFRESH_STATE"


@pytest.mark.django_db
def test_non_owner_cannot_refresh(organizer_user, participant_user) -> None:
    event = _hydrate_then_set(organizer_user, status=EventStatus.ACTIVE.value)
    resolved = _resolved(_bundle(), _DIGEST_A)
    with pytest.raises(CTFPermissionError):
        refresh_event_ctf_content(event.pk, resolved, actor_id=participant_user.pk, expected_current_digest=_DIGEST_A)


@pytest.mark.django_db
def test_draft_full_reconcile_adds_removes_and_renames(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(_bundle(), _DIGEST_A), actor_id=organizer_user.pk)
    original_one = CTFChallenge.objects.get(event=event, source_id="challenge-one")

    result = refresh_event_ctf_content(
        event.pk,
        # rename one, drop two, add three (three requires one)
        _resolved(_bundle(one_name="One Renamed", include_two=False, include_three=True), _DIGEST_B),
        actor_id=organizer_user.pk,
        expected_current_digest=_DIGEST_A,
    )

    assert result.outcome == "refreshed"
    one = CTFChallenge.objects.get(event=event, source_id="challenge-one")
    assert one.pk == original_one.pk
    assert one.name == "One Renamed"
    assert not CTFChallenge.objects.filter(event=event, source_id="challenge-two").exists()
    three = CTFChallenge.objects.get(event=event, source_id="challenge-three")
    assert three.prerequisites.get().required_challenge.source_id == "challenge-one"
    receipt = CTFContentHydrationReceipt.objects.get(event=event)
    assert receipt.challenge_count == 2


@pytest.mark.django_db
def test_structural_reconcile_refused_when_scoring_ledger_exists(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(_bundle(), _DIGEST_A), actor_id=organizer_user.pk)
    challenge = CTFChallenge.objects.get(event=event, source_id="challenge-one")
    from ctf.models import CTFParticipant, CTFSubmission

    participant = CTFParticipant.objects.create(event=event, email="p@test.com", name="P")
    CTFSubmission.objects.create(
        participant=participant, challenge=challenge, submitted_flag="x", is_correct=True, points_awarded=100
    )

    resolved = _resolved(_bundle(include_three=True), _DIGEST_B)
    with pytest.raises(CTFStateError) as error:
        refresh_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk, expected_current_digest=_DIGEST_A)
    assert error.value.code == "CTF_CONTENT_REFRESH_STATE"
