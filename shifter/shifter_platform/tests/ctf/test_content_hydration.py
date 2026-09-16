"""Atomic hydration, retry, drift, and activation tests."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from ctf.content_bundle import parse_ctf_content_bundle
from ctf.enums import EventStatus
from ctf.exceptions import CTFStateError, CTFValidationError
from ctf.models import CTFChallenge, CTFContentHydrationReceipt, CTFEvent, CTFFlag, CTFHint
from ctf.services.challenge import update_challenge
from ctf.services.content_hydration import assert_event_content_hydration_ready, hydrate_event_ctf_content
from ctf.services.content_resolution import HydrationSourceEvidence, ResolvedCtfContent
from ctf.services.event import (
    activate_event,
    create_event,
    open_registration,
    pause_event,
    resume_event,
    start_event,
)
from shared.schemas.ctf_content_reference import load_ctf_content_references_json


def _bundle():
    raw = json.dumps(
        {
            "contract": "shifter-ctf-content/v1",
            "scenario_id": "scenario-one",
            "challenges": [
                {
                    "id": "challenge-one",
                    "name": "Challenge One",
                    "description": "Inspect the portal.",
                    "category": "Module 1",
                    "points": 100,
                    "difficulty": "easy",
                    "order": 1,
                    "flags": [{"type": "static", "value": "TEST{one}", "order": 0}],
                    "hints": [{"text": "Start with the portal.", "penalty": 0, "order": 1}],
                    "prerequisites": [],
                },
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
                },
            ],
        }
    ).encode()
    return parse_ctf_content_bundle(raw)


def _resolved() -> ResolvedCtfContent:
    return ResolvedCtfContent(
        bundle=_bundle(),
        evidence=HydrationSourceEvidence(
            reference_contract="shifter-ctf-content-references/v1",
            declared_digest=f"sha256:{'a' * 64}",
            object_key_fingerprint="b" * 64,
            object_identity_fingerprint="c" * 64,
            object_size_bytes=1024,
        ),
    )


def _event(organizer_user) -> CTFEvent:
    now = timezone.now()
    return CTFEvent.objects.create(
        name="Hydration Test",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=now + timedelta(hours=1),
        event_end=now + timedelta(hours=2),
        scenario_id="scenario-one",
    )


@pytest.mark.django_db
def test_hydration_creates_complete_graph_and_exact_retry_is_noop(organizer_user) -> None:
    event = _event(organizer_user)
    first = hydrate_event_ctf_content(event.pk, _resolved(), actor_id=organizer_user.pk)
    second = hydrate_event_ctf_content(event.pk, _resolved(), actor_id=organizer_user.pk)

    assert first.created is True
    assert second.created is False
    assert CTFChallenge.objects.filter(event=event).count() == 2
    assert CTFFlag.objects.filter(challenge__event=event).count() == 2
    assert CTFHint.objects.filter(challenge__event=event).count() == 1
    challenge_two = CTFChallenge.objects.get(event=event, source_id="challenge-two")
    assert challenge_two.prerequisites.get().required_challenge.source_id == "challenge-one"


@pytest.mark.django_db
def test_authorized_edit_marks_receipt_drifted(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(), actor_id=organizer_user.pk)
    challenge = CTFChallenge.objects.get(event=event, source_id="challenge-one")

    update_challenge(challenge.pk, {"description": "Authorized correction."}, actor_id=organizer_user.pk)

    receipt = CTFContentHydrationReceipt.objects.get(event=event)
    assert receipt.state == CTFContentHydrationReceipt.State.DRIFTED
    assert receipt.drift_reason == "challenge_updated"
    resolved = _resolved()
    with pytest.raises(CTFStateError):
        hydrate_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk)


@pytest.mark.django_db
def test_hydration_rolls_back_complete_graph_on_failure(organizer_user, monkeypatch) -> None:
    event = _event(organizer_user)
    monkeypatch.setattr("ctf.services.hint.add_hint", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))
    resolved = _resolved()

    with pytest.raises(RuntimeError):
        hydrate_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk)

    assert not CTFChallenge.objects.filter(event=event).exists()
    assert not CTFContentHydrationReceipt.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_foreign_content_is_not_merged(organizer_user) -> None:
    event = _event(organizer_user)
    CTFChallenge.objects.create(
        event=event,
        name="Foreign",
        description="Existing",
        category="misc",
        points=10,
    )
    resolved = _resolved()
    with pytest.raises(CTFStateError) as error:
        hydrate_event_ctf_content(event.pk, resolved, actor_id=organizer_user.pk)
    assert error.value.code == "CTF_CONTENT_FOREIGN_STATE"
    assert CTFChallenge.objects.filter(event=event).count() == 1


def _configured_references():
    return load_ctf_content_references_json(
        json.dumps(
            {
                "contract": "shifter-ctf-content-references/v1",
                "references": [
                    {
                        "scenario_id": "scenario-one",
                        "object_key": "ctf/content-bundles/aa/bundle.json",
                        "digest": f"sha256:{'a' * 64}",
                    }
                ],
            }
        ),
        prefix="ctf/content-bundles",
    )


@pytest.mark.django_db
def test_both_activation_paths_require_pristine_receipt(organizer_user) -> None:
    event = _event(organizer_user)
    with override_settings(CTF_CONTENT_REFERENCES=_configured_references()):
        assert open_registration(event) is True
        event.refresh_from_db()
        with pytest.raises(CTFStateError) as error:
            start_event(event.pk)
        assert error.value.code == "CTF_CONTENT_NOT_READY"
        assert activate_event(event) is False
        event.refresh_from_db()
        assert event.status == EventStatus.REGISTRATION.value


@pytest.mark.django_db
def test_removed_reference_does_not_authorize_managed_content(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(), actor_id=organizer_user.pk)
    assert open_registration(event) is True
    event.refresh_from_db()

    with override_settings(CTF_CONTENT_REFERENCES=load_ctf_content_references_json("", prefix="ctf/content-bundles")):
        with pytest.raises(CTFStateError) as error:
            assert_event_content_hydration_ready(event)
        assert error.value.code == "CTF_CONTENT_NOT_READY"
        with pytest.raises(CTFStateError):
            start_event(event.pk)
        assert activate_event(event) is False


@pytest.mark.django_db
def test_resume_re_enforces_content_readiness(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(), actor_id=organizer_user.pk)
    with override_settings(CTF_CONTENT_REFERENCES=_configured_references()):
        assert open_registration(event) is True
        event.refresh_from_db()
        assert activate_event(event) is True
        event.refresh_from_db()
        assert pause_event(event) is True
        event.refresh_from_db()
        assert event.status == EventStatus.PAUSED.value

        # A paused event whose configured content is no longer ready must not
        # resume back to ACTIVE (issue #1971 bypass fix).
        with override_settings(
            CTF_CONTENT_REFERENCES=load_ctf_content_references_json("", prefix="ctf/content-bundles")
        ):
            assert resume_event(event) is False
            event.refresh_from_db()
            assert event.status == EventStatus.PAUSED.value

        # With the configured reference restored, resume succeeds.
        assert resume_event(event) is True
        event.refresh_from_db()
        assert event.status == EventStatus.ACTIVE.value


@pytest.mark.django_db
def test_event_creation_composes_hydration_atomically(organizer_user, monkeypatch) -> None:
    resolved = _resolved()
    monkeypatch.setattr("ctf.bridges.cms_list_scenarios", lambda _user: [("scenario-one", "Scenario One")])
    monkeypatch.setattr(
        "ctf.services.content_resolution.resolve_scenario_ctf_content",
        lambda scenario_id: resolved if scenario_id == "scenario-one" else None,
    )
    now = timezone.now()
    with override_settings(CTF_CONTENT_REFERENCES=_configured_references()):
        event = create_event(
            organizer_user,
            {
                "name": "Created With Content",
                "event_start": now + timedelta(hours=1),
                "event_end": now + timedelta(hours=2),
                "scenario_id": "scenario-one",
            },
        )
    assert event.challenges.count() == 2
    assert CTFContentHydrationReceipt.objects.filter(event=event).exists()


@pytest.mark.django_db
def test_event_creation_authorizes_configured_scenario_before_resolution(organizer_user, monkeypatch) -> None:
    monkeypatch.setattr(
        "ctf.services.content_resolution.resolve_scenario_ctf_content",
        lambda _scenario_id: pytest.fail("resolver must not run"),
    )
    monkeypatch.setattr("ctf.bridges.cms_list_scenarios", lambda _user: [])
    now = timezone.now()
    event_data = {
        "name": "Unauthorized Content",
        "event_start": now + timedelta(hours=1),
        "event_end": now + timedelta(hours=2),
        "scenario_id": "scenario-one",
    }
    references = _configured_references()
    with (
        override_settings(CTF_CONTENT_REFERENCES=references),
        pytest.raises(CTFValidationError) as error,
    ):
        create_event(organizer_user, event_data)
    assert error.value.code == "CTF_SCENARIO_NOT_AVAILABLE"
