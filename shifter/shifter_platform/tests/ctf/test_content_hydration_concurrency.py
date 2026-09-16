"""PostgreSQL lock proof for managed CTF content hydration and activation."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from ctf.content_bundle import parse_ctf_content_bundle
from ctf.enums import EventStatus
from ctf.exceptions import CTFError
from ctf.models import CTFChallenge, CTFContentHydrationReceipt, CTFEvent
from ctf.services.challenge import update_challenge
from ctf.services.content_hydration import (
    ContentHydrationResult,
    assert_event_content_hydration_ready,
    hydrate_event_ctf_content,
)
from ctf.services.content_resolution import HydrationSourceEvidence, ResolvedCtfContent
from ctf.services.event import open_registration, start_event
from shared.schemas.ctf_content_reference import load_ctf_content_references_json

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db(transaction=True),
]


def _resolved() -> ResolvedCtfContent:
    raw = json.dumps(
        {
            "contract": "shifter-ctf-content/v1",
            "scenario_id": "scenario-concurrency",
            "challenges": [
                {
                    "id": "challenge-one",
                    "name": "Challenge One",
                    "description": "Original description.",
                    "category": "Module 1",
                    "points": 100,
                    "difficulty": "easy",
                    "order": 1,
                    "flags": [{"type": "static", "value": "TEST{one}", "order": 0}],
                    "hints": [],
                    "prerequisites": [],
                }
            ],
        }
    ).encode()
    return ResolvedCtfContent(
        bundle=parse_ctf_content_bundle(raw),
        evidence=HydrationSourceEvidence(
            reference_contract="shifter-ctf-content-references/v1",
            declared_digest=f"sha256:{'a' * 64}",
            object_key_fingerprint="b" * 64,
            object_identity_fingerprint="c" * 64,
            object_size_bytes=len(raw),
        ),
    )


def _references():
    return load_ctf_content_references_json(
        json.dumps(
            {
                "contract": "shifter-ctf-content-references/v1",
                "references": [
                    {
                        "scenario_id": "scenario-concurrency",
                        "object_key": "ctf/content-bundles/concurrency/bundle.json",
                        "digest": f"sha256:{'a' * 64}",
                    }
                ],
            }
        ),
        prefix="ctf/content-bundles",
    )


def _event(organizer_user) -> CTFEvent:
    now = timezone.now()
    return CTFEvent.objects.create(
        name="Content Concurrency Event",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=now + timedelta(hours=1),
        event_end=now + timedelta(hours=2),
        scenario_id="scenario-concurrency",
    )


def _race_hydration(
    event_id: UUID,
    actor_id: int,
    barrier: threading.Barrier,
) -> ContentHydrationResult:
    barrier.wait(timeout=10)
    try:
        return hydrate_event_ctf_content(event_id, _resolved(), actor_id=actor_id)
    finally:
        connection.close()


def _race_activation(event_id: UUID, barrier: threading.Barrier) -> tuple[str, CTFError | None]:
    barrier.wait(timeout=10)
    try:
        start_event(event_id)
    except CTFError as exc:
        return ("error", exc)
    finally:
        connection.close()
    return ("ok", None)


def _race_edit(
    challenge_id: UUID,
    actor_id: int,
    barrier: threading.Barrier,
) -> tuple[str, CTFError | None]:
    barrier.wait(timeout=10)
    try:
        update_challenge(
            challenge_id,
            {"description": "Concurrent edit."},
            actor_id=actor_id,
        )
    except CTFError as exc:
        return ("error", exc)
    finally:
        connection.close()
    return ("ok", None)


def test_concurrent_exact_hydration_creates_one_graph(organizer_user) -> None:
    event = _event(organizer_user)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [executor.submit(_race_hydration, event.pk, organizer_user.pk, barrier) for _ in range(2)]
        results = [future.result(timeout=30) for future in outcomes]

    assert sorted(result.created for result in results) == [False, True]
    assert CTFChallenge.objects.filter(event=event).count() == 1
    assert CTFContentHydrationReceipt.objects.filter(event=event).count() == 1


def test_readiness_service_owns_its_postgres_lock_transaction(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(), actor_id=organizer_user.pk)

    with override_settings(CTF_CONTENT_REFERENCES=_references()):
        assert_event_content_hydration_ready(event)


def test_activation_and_edit_never_commit_active_stale_content(organizer_user) -> None:
    event = _event(organizer_user)
    hydrate_event_ctf_content(event.pk, _resolved(), actor_id=organizer_user.pk)
    challenge = CTFChallenge.objects.get(event=event, source_id="challenge-one")
    assert open_registration(event) is True

    barrier = threading.Barrier(2)
    with (
        override_settings(CTF_CONTENT_REFERENCES=_references()),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        activation = executor.submit(_race_activation, event.pk, barrier)
        edit = executor.submit(_race_edit, challenge.pk, organizer_user.pk, barrier)
        activation_outcome = activation.result(timeout=30)
        edit_outcome = edit.result(timeout=30)

    event.refresh_from_db()
    challenge.refresh_from_db()
    receipt = CTFContentHydrationReceipt.objects.get(event=event)

    if event.status == EventStatus.ACTIVE.value:
        assert activation_outcome[0] == "ok"
        assert edit_outcome[0] == "error"
        assert challenge.description == "Original description."
        assert receipt.state == CTFContentHydrationReceipt.State.PRISTINE
    else:
        assert event.status == EventStatus.REGISTRATION.value
        assert activation_outcome[0] == "error"
        assert edit_outcome[0] == "ok"
        assert challenge.description == "Concurrent edit."
        assert receipt.state == CTFContentHydrationReceipt.State.DRIFTED
