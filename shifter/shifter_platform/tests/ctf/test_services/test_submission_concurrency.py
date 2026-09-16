"""PostgreSQL concurrency proof for `ctf.services.submission.submit_flag()`
(#1135, #1137, #1182).

`submit_flag()` serializes the already-solved / attempt-limit / cooldown
checks and the `CTFSubmission` INSERT inside `transaction.atomic()`, guarded
by `CTFParticipant.objects.select_for_update()`. `tests/ctf/test_services/
test_submission.py::TestCorrectSubmissionUniqueness` proves the *sequential*
shape of that guard (an existing correct row blocks a second submit, and the
partial unique index is a DB backstop), but SQLite — the default test
backend — has no real row-level locking, so it cannot prove the lock
actually *serializes concurrent* requests.

This module races real threads, each with its own DB connection, against a
real PostgreSQL instance (selected by the settings-owned `TEST_DB_BACKEND=postgres`
selector plus pytest-django's native test-database lifecycle) to prove the
submission-control guarantees hold under genuine concurrency for all three
paths: duplicate-solve, attempt-limit lockout, and submission cooldown.

What each class actually proves differs by path, because only one path has a
DB backstop:

- **Attempt-limit and cooldown** have no DB constraint behind them, so the
  only thing that can stop concurrent over-counting is the row lock. Delete
  `select_for_update()` and every racer reads the same pre-check state and is
  admitted, blowing the cap / cooldown — so those two classes isolate the row
  lock's *own* contribution and fail if it is removed.
- **Duplicate-solve** is defense-in-depth: the row lock *and* the
  `ctf_unique_correct_submission` partial unique index both enforce
  at-most-one-correct. Under READ COMMITTED the constraint alone would still
  reject all-but-one INSERT (mapped to `CTF_ALREADY_SOLVED`), so
  `TestConcurrentCorrectSubmissions` proves the *system-level*
  at-most-one-correct-solve guarantee under concurrency, not the lock in
  isolation. (The lock is a single call guarding all three paths, so a
  regression that drops it is still caught by the two classes above.)

Marked `postgres` so the default SQLite suite excludes it (`-m "not postgres"`),
and `django_db(transaction=True)` so writes are real commits visible across
threads/connections (not rolled back inside a shared wrapping transaction).
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.db import connection
from django.utils import timezone

from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus, ParticipantStatus
from ctf.exceptions import CTFError
from ctf.extensions import register_flag_validator
from ctf.models import CTFChallenge, CTFEvent, CTFFlag, CTFParticipant, CTFReceiptConsumption, CTFSubmission
from ctf.services.challenge import hash_flag
from ctf.services.submission import submit_flag
from ctf.validators import ReceiptVerifierProfile, register_receipt_profile
from engine.models import Range
from engine.models import Request as EngineRequest
from engine.services import register_receipt_verifier
from shared.enums import RangeSource, RequestType, ResourceStatus
from shared.receipt_validation import (
    ReceiptKeyMode,
    ReceiptRegistrationDemand,
    VerifiedReceiptEvidence,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

# `postgres`-marked so the SQLite lane excludes it by marker (`-m "not
# postgres"`), not a per-test skip: SQLite has no real row-level locking, so
# `select_for_update()` is a no-op there and these races would assert against
# meaningless behavior. In the PostgreSQL lane the settings-owned
# `TEST_DB_BACKEND=postgres` selector points the ORM at a real PostgreSQL
# backend and pytest-django creates/migrates the per-worker test database.
# Selecting a `postgres`-marked test under the wrong backend is a configuration
# error (the root-conftest guard fails closed), not a silent skip.
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db(transaction=True),
]

# Correctness is decided by the real production verification path
# (`verify_flag` -> `verify_single_flag` against a genuine bcrypt-hashed
# `CTFFlag` row), not by patching the first-party `verify_flag` seam. That
# keeps these tests behavioral and satisfies the boundary-mock policy
# (ADR-019): a correct submission is one that submits `CORRECT_FLAG`, a wrong
# one submits anything else.
CORRECT_FLAG = "FLAG{concurrency-proof}"


def _add_static_flag(challenge: CTFChallenge) -> None:
    """Attach a real hashed static flag so `verify_flag()` runs for real."""
    CTFFlag.objects.create(challenge=challenge, flag_hash=hash_flag(CORRECT_FLAG))


def _race(
    participant_id: UUID,
    challenge_id: UUID,
    submitted_flag: str,
    barrier: threading.Barrier,
) -> tuple[str, CTFSubmission | CTFError]:
    """Call `submit_flag()` from a worker thread, synchronized on `barrier`.

    Returns `("ok", CTFSubmission)` on success or `("error", CTFError)` on a
    rejection, so the caller can classify every outcome without exceptions
    crossing thread boundaries. Each worker thread gets its own DB
    connection (Django connections are thread-local); it is closed before
    the thread returns so ThreadPoolExecutor workers do not leak connections.
    """
    barrier.wait(timeout=10)
    try:
        submission = submit_flag(participant_id, challenge_id, submitted_flag)
    except CTFError as exc:
        return ("error", exc)
    finally:
        connection.close()
    return ("ok", submission)


@pytest.fixture
def event(db, organizer_user: User) -> CTFEvent:
    """Active event with no submission cooldown (isolates the scenario under test)."""
    return CTFEvent.objects.create(
        name="Submission Concurrency Event",
        created_by=organizer_user,
        status=EventStatus.ACTIVE.value,
        event_start=timezone.now() - timedelta(hours=1),
        event_end=timezone.now() + timedelta(hours=7),
        scenario_id="basic",
        submission_cooldown_seconds=0,
    )


@pytest.fixture
def challenge(db, event: CTFEvent) -> CTFChallenge:
    """Challenge with unlimited attempts (max_attempts=0, the model default)."""
    obj = CTFChallenge.objects.create(
        event=event,
        name="Submission Concurrency Challenge",
        description="Race target",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_format="FLAG{...}",
    )
    _add_static_flag(obj)
    return obj


@pytest.fixture
def participant(db, event: CTFEvent, participant_user: User) -> CTFParticipant:
    """Active participant in the race event."""
    return CTFParticipant.objects.create(
        event=event,
        user=participant_user,
        email=participant_user.email,
        name="Racer",
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


class TestConcurrentCorrectSubmissions:
    """(a) Racing correct submissions for the same (participant, challenge)
    must resolve to exactly one solve under genuine concurrency.

    This proves the *system-level* at-most-one-correct-solve guarantee — the
    row lock and the `ctf_unique_correct_submission` partial unique index
    acting together as defense-in-depth — not the row lock in isolation. Under
    READ COMMITTED the partial unique index alone would reject all-but-one
    concurrent INSERT (mapped to `CTF_ALREADY_SOLVED`), so this class would
    still pass if only the constraint held. The row lock's own contribution is
    isolated by the attempt-limit and cooldown classes below, whose paths have
    no DB backstop; since the lock is a single call guarding all three paths, a
    regression that drops it is caught there. See the module docstring."""

    RACERS = 8

    def test_exactly_one_correct_submission_wins(self, participant, challenge):
        barrier = threading.Barrier(self.RACERS)
        with ThreadPoolExecutor(max_workers=self.RACERS) as executor:
            futures = [
                executor.submit(_race, participant.id, challenge.id, CORRECT_FLAG, barrier) for _ in range(self.RACERS)
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        wins = [outcome for outcome in outcomes if outcome[0] == "ok"]
        losses = [outcome for outcome in outcomes if outcome[0] == "error"]

        assert len(wins) == 1, "exactly one racer should win the solve"
        assert len(losses) == self.RACERS - 1
        assert all(exc.code == "CTF_ALREADY_SOLVED" for _, exc in losses)

        # Losers are rejected either by the under-lock already-solved pre-check
        # (serialized racer sees the committed correct row) or, in the
        # interleaving where they pass the pre-check, by the partial unique
        # index at INSERT (mapped to CTF_ALREADY_SOLVED). Either way exactly one
        # row exists — not just one *correct* row — because the losing path
        # never commits an INSERT.
        all_rows = CTFSubmission.objects.filter(participant=participant, challenge=challenge)
        assert all_rows.count() == 1
        assert all_rows.get().is_correct is True

        participant.refresh_from_db()
        assert participant.cached_score == challenge.points
        assert participant.cached_solve_count == 1


class TestConcurrentAttemptLimitLockout:
    """(b) Racing wrong submissions past `challenge.max_attempts` in the
    default lockout mode must not exceed the cap under concurrency."""

    MAX_ATTEMPTS = 3
    RACERS = 10

    @pytest.fixture
    def challenge(self, db, event: CTFEvent) -> CTFChallenge:
        obj = CTFChallenge.objects.create(
            event=event,
            name="Attempt Limit Concurrency Challenge",
            description="Race target",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_format="FLAG{...}",
            max_attempts=self.MAX_ATTEMPTS,
        )
        _add_static_flag(obj)
        return obj

    def test_attempt_cap_holds_under_concurrency(self, participant, challenge):
        barrier = threading.Barrier(self.RACERS)
        with ThreadPoolExecutor(max_workers=self.RACERS) as executor:
            futures = [
                executor.submit(_race, participant.id, challenge.id, f"FLAG{{wrong-{i}}}", barrier)
                for i in range(self.RACERS)
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        wins = [outcome for outcome in outcomes if outcome[0] == "ok"]
        losses = [outcome for outcome in outcomes if outcome[0] == "error"]

        assert len(wins) == self.MAX_ATTEMPTS, "attempt cap must not be exceeded under concurrency"
        assert len(losses) == self.RACERS - self.MAX_ATTEMPTS
        assert all(exc.details.get("attempt_limit_mode") == "lockout" for _, exc in losses)
        assert all(exc.details.get("max_attempts") == self.MAX_ATTEMPTS for _, exc in losses)

        rows = CTFSubmission.objects.filter(participant=participant, challenge=challenge)
        assert rows.count() == self.MAX_ATTEMPTS, "rejected attempts must not create extra rows past the cap"
        assert not rows.filter(is_correct=True).exists()

        participant.refresh_from_db()
        assert participant.cached_score == 0
        assert participant.cached_solve_count == 0


class TestConcurrentSubmissionCooldown:
    """(c) Racing submissions within `event.submission_cooldown_seconds`
    must not let more submissions through than the cooldown permits."""

    COOLDOWN_SECONDS = 30
    RACERS = 8

    @pytest.fixture
    def event(self, db, organizer_user: User) -> CTFEvent:
        return CTFEvent.objects.create(
            name="Cooldown Concurrency Event",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="basic",
            submission_cooldown_seconds=self.COOLDOWN_SECONDS,
        )

    def test_cooldown_holds_under_concurrency(self, participant, challenge):
        barrier = threading.Barrier(self.RACERS)
        with ThreadPoolExecutor(max_workers=self.RACERS) as executor:
            futures = [
                executor.submit(_race, participant.id, challenge.id, f"FLAG{{wrong-{i}}}", barrier)
                for i in range(self.RACERS)
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        wins = [outcome for outcome in outcomes if outcome[0] == "ok"]
        losses = [outcome for outcome in outcomes if outcome[0] == "error"]

        assert len(wins) == 1, "cooldown must allow exactly one submission through per window"
        assert len(losses) == self.RACERS - 1
        assert all("retry_after_seconds" in exc.details for _, exc in losses)
        assert all(exc.details.get("cooldown_seconds") == self.COOLDOWN_SECONDS for _, exc in losses)

        rows = CTFSubmission.objects.filter(participant=participant, challenge=challenge)
        assert rows.count() == 1, "rejected attempts must not create rows beyond the cooldown policy"

        participant.refresh_from_db()
        assert participant.cached_score == 0
        assert participant.cached_solve_count == 0


class TestConcurrentReceiptRedemption:
    """Receipt verification still admits exactly one durable score/consumption."""

    RACERS = 8
    PROFILE_ID = "receipt-race-profile"
    OBJECTIVE_ID = "receipt-race-objective"
    FLAG_TYPE = "receipt-race"

    @pytest.fixture
    def event(self, db, organizer_user: User) -> CTFEvent:
        return CTFEvent.objects.create(
            name="Receipt Concurrency Event",
            created_by=organizer_user,
            status=EventStatus.ACTIVE.value,
            event_start=timezone.now() - timedelta(hours=1),
            event_end=timezone.now() + timedelta(hours=7),
            scenario_id="receipt-race",
            submission_cooldown_seconds=0,
        )

    @pytest.fixture
    def receipt_profile(self, monkeypatch):
        from ctf.validators import _receipt_profiles

        monkeypatch.setattr(_receipt_profiles, "_PROFILES", {})
        profile = ReceiptVerifierProfile(
            profile_id=self.PROFILE_ID,
            deployment_id="postgres-race",
            provider_contract="race-v1",
            endpoint_url="https://proof.example.test/v1/platform/receipts/verify",
            audience="https://proof.example.test",
            service_auth_secret_ref="projects/test/secrets/receipt-race/versions/1",
            issuer_id="race-proof",
            allowed_key_modes=(ReceiptKeyMode.REMOTE_SYMMETRIC,),
            allowed_algorithms=("hmac-sha256",),
            permitted_objectives=(self.OBJECTIVE_ID,),
        )
        register_receipt_profile(profile)
        return profile

    @pytest.fixture
    def challenge(self, db, event: CTFEvent, receipt_profile) -> CTFChallenge:
        from ctf.extensions import _flag_validators, _server_context_flag_validators

        def verify_receipt(_flag, _submitted, context):
            return VerifiedReceiptEvidence(
                receipt_id="shared-race-receipt",
                issuer_id=context.issuer_id,
                expires_at=timezone.now() + timedelta(minutes=5),
                context=context,
            )

        register_flag_validator(self.FLAG_TYPE, verify_receipt, supports_server_context=True)
        challenge = CTFChallenge.objects.create(
            event=event,
            name="Receipt Race Challenge",
            description="Race one bound receipt",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.HARD.value,
        )
        CTFFlag.objects.create(
            challenge=challenge,
            flag_hash="receipt-context",
            flag_type=self.FLAG_TYPE,
            validator_config={
                "protocol": "receipt-v1",
                "profile_id": self.PROFILE_ID,
                "objective_id": self.OBJECTIVE_ID,
            },
        )
        yield challenge
        _flag_validators.pop(self.FLAG_TYPE, None)
        _server_context_flag_validators.discard(self.FLAG_TYPE)

    @pytest.fixture
    def participant(self, db, event: CTFEvent, participant_user: User, receipt_profile) -> CTFParticipant:
        request_id = uuid4()
        cms_request = CmsRequest.objects.create(
            request_id=request_id,
            request_type=RequestType.RANGE.value,
            user=participant_user,
            workspace_id=1,
        )
        engine_request = EngineRequest.objects.create(
            request_id=request_id,
            request_type=RequestType.RANGE.value,
            user=participant_user,
        )
        Range.objects.create(
            workspace_id=1,
            request=engine_request,
            user=participant_user,
            cms_user_id=participant_user.pk,
            status=Range.Status.READY,
            provisioner_operation="provision",
            provisioner_operation_id=request_id,
        )
        instance = RangeInstance.objects.create(
            request=cms_request,
            scenario_id="receipt-race",
            user_id=participant_user.pk,
            workspace_id=1,
            status=ResourceStatus.READY.value,
            range_source=RangeSource.CTF.value,
            expires_at=timezone.now() + timedelta(hours=1),
            maximum_expires_at=timezone.now() + timedelta(hours=1),
        )
        participant = CTFParticipant.objects.create(
            event=event,
            user=participant_user,
            email=participant_user.email,
            name="Receipt Racer",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
            range_instance_id=instance.pk,
            range_status=ResourceStatus.READY.value,
        )
        register_receipt_verifier(
            request_id,
            request_id,
            ReceiptRegistrationDemand(
                deployment_id=receipt_profile.deployment_id,
                profile_id=receipt_profile.profile_id,
                provider_contract=receipt_profile.provider_contract,
                ctf_event_id=event.pk,
                ctf_participant_id=participant.pk,
                objectives=(self.OBJECTIVE_ID,),
                issuer_id=receipt_profile.issuer_id,
                provider_range_namespace="range-race",
                provider_participant_namespace="participant-race",
                key_mode=ReceiptKeyMode.REMOTE_SYMMETRIC,
                algorithm_id="hmac-sha256",
                key_id="race-key-v1",
                reset_generation=0,
                secret_version_ref="projects/test/secrets/receipt-race-key/versions/1",
            ),
        )
        return participant

    def test_exactly_one_receipt_submission_scores_and_consumes(self, participant, challenge):
        barrier = threading.Barrier(self.RACERS)
        with ThreadPoolExecutor(max_workers=self.RACERS) as executor:
            futures = [
                executor.submit(_race, participant.id, challenge.id, "PENR1.shared", barrier)
                for _ in range(self.RACERS)
            ]
            outcomes = [future.result(timeout=30) for future in futures]

        wins = [outcome for outcome in outcomes if outcome[0] == "ok"]
        losses = [outcome for outcome in outcomes if outcome[0] == "error"]
        assert len(wins) == 1
        assert len(losses) == self.RACERS - 1
        assert all(exc.code == "CTF_ALREADY_SOLVED" for _, exc in losses)
        assert CTFReceiptConsumption.objects.count() == 1
        assert CTFSubmission.objects.filter(participant=participant, challenge=challenge).count() == 1

        participant.refresh_from_db()
        assert participant.cached_score == challenge.points
        assert participant.cached_solve_count == 1
