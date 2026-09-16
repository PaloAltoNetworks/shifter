"""PostgreSQL lock proof for in-place managed CTF content refresh (issue #1971).

Proves the optimistic-fence cutover under real concurrency: the refresh takes an
event row lock, so two racing refreshes against the same expected digest
serialize and exactly one wins; the loser, after waiting for the lock, sees the
already-advanced digest and loses with a stale-revision conflict rather than
applying a second, divergent revision. Post-commit reads observe the new flag
set.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID

import pytest
from django.db import connection
from django.utils import timezone

from ctf.content_bundle import parse_ctf_content_bundle
from ctf.enums import EventStatus
from ctf.exceptions import CTFError
from ctf.models import CTFContentHydrationReceipt, CTFEvent, CTFFlag
from ctf.services.challenge import verify_single_flag
from ctf.services.content_hydration import hydrate_event_ctf_content
from ctf.services.content_refresh import refresh_event_ctf_content
from ctf.services.content_resolution import HydrationSourceEvidence, ResolvedCtfContent

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db(transaction=True),
]

_DIGEST_A = f"sha256:{'a' * 64}"
_DIGEST_B = f"sha256:{'b' * 64}"
_SCENARIO = "scenario-refresh-concurrency"


def _resolved(digest: str, *, flag: str = "TEST{one}") -> ResolvedCtfContent:
    raw = json.dumps(
        {
            "contract": "shifter-ctf-content/v1",
            "scenario_id": _SCENARIO,
            "challenges": [
                {
                    "id": "challenge-one",
                    "name": "Challenge One",
                    "description": "Original description.",
                    "category": "Module 1",
                    "points": 100,
                    "difficulty": "easy",
                    "order": 1,
                    "flags": [{"type": "static", "value": flag, "order": 0}],
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
            declared_digest=digest,
            object_key_fingerprint="b" * 64,
            object_identity_fingerprint="c" * 64,
            object_size_bytes=len(raw),
        ),
    )


def _active_managed_event(organizer_user) -> CTFEvent:
    now = timezone.now()
    event = CTFEvent.objects.create(
        name="Refresh Concurrency Event",
        created_by=organizer_user,
        status=EventStatus.DRAFT.value,
        event_start=now + timedelta(hours=1),
        event_end=now + timedelta(hours=2),
        scenario_id=_SCENARIO,
    )
    hydrate_event_ctf_content(event.pk, _resolved(_DIGEST_A), actor_id=organizer_user.pk)
    event.status = EventStatus.ACTIVE.value
    event.save(update_fields=["status", "updated_at"])
    return event


def _race_refresh(
    event_id: UUID,
    actor_id: int,
    resolved: ResolvedCtfContent,
    expected_digest: str,
    barrier: threading.Barrier,
) -> tuple[str, CTFError | None]:
    barrier.wait(timeout=10)
    try:
        refresh_event_ctf_content(
            event_id,
            resolved,
            actor_id=actor_id,
            expected_current_digest=expected_digest,
        )
    except CTFError as exc:
        return ("error", exc)
    finally:
        connection.close()
    return ("ok", None)


def test_concurrent_refresh_fence_admits_exactly_one(organizer_user) -> None:
    event = _active_managed_event(organizer_user)
    barrier = threading.Barrier(2)
    target = _resolved(_DIGEST_B, flag="TEST{one-fixed}")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_race_refresh, event.pk, organizer_user.pk, target, _DIGEST_A, barrier) for _ in range(2)
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    statuses = sorted(outcome[0] for outcome in outcomes)
    assert statuses == ["error", "ok"]  # the row lock serializes; exactly one wins

    loser = next(outcome for outcome in outcomes if outcome[0] == "error")
    assert loser[1].code == "CTF_CONTENT_REFRESH_CONFLICT"  # stale fence loses after the lock

    receipt = CTFContentHydrationReceipt.objects.get(event=event)
    assert receipt.declared_digest == _DIGEST_B
    assert receipt.state == CTFContentHydrationReceipt.State.PRISTINE

    # Post-commit reads observe the new committed flag set, not the old one.
    flag = CTFFlag.objects.get(challenge__event=event, challenge__source_id="challenge-one")
    assert verify_single_flag(flag, "TEST{one-fixed}") is True
    assert verify_single_flag(flag, "TEST{one}") is False
