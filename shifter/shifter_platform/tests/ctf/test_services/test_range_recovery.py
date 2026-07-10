"""Tests for CTF destroyed-participant-range recovery (issue #1018).

DB-backed integration-style tests (per the repo's OOM lesson: fixtures and
real rows over many micro-tests with inline mocks). Per ADR-019's
boundary-mock policy, first-party ``ctf.bridges`` / ``cms.services`` targets
are not patched here at all: the ``rebuild`` strategy drives the *real*
``ctf.bridges.cms_create_range`` -> ``cms.services.create_range`` ->
``engine.services.create_range`` stack (engine ECS is unconfigured in test
settings, so provisioning/teardown dispatch is a no-op -- see
``tests/cms/test_services_range.py``), and old-range teardown drives the real
``ctf.bridges.cms_destroy_range`` -> ``cms.services.destroy_range`` ->
``engine.services.destroy_range_by_request`` stack. The only mock in this
file is at the ECS/cloud boundary (``engine.ecs.start_range_teardown``), used
once to simulate a transient provider failure for the idempotent-retry test.

Everything else (RangeInstance/Range/Request rows, ownership reassignment,
participant repointing, audit) runs for real so cross-app resolution
(``engine.models.Range.resolve_active_for_instance``) is genuinely exercised.

The old range is always destroyed -- there is no disposition/forensics
concept (owner decision, #1018 revised plan). ``reassign_spare`` now consumes
an event-scoped ``CTFSpareRange`` pool row instead of scanning CMS for any
unowned same-scenario range.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from cms.models import AgentConfig, OperatingSystem, RangeInstance
from cms.models import Request as CmsRequest
from ctf.enums import (
    EventStatus,
    ParticipantStatus,
    RecoveryFailureCategory,
    RecoveryPhase,
    RecoveryStrategy,
    SpareRangeStatus,
)
from ctf.exceptions import CTFNotFoundError, CTFRangeError, CTFValidationError
from ctf.models import (
    CTFAward,
    CTFBracket,
    CTFEvent,
    CTFParticipant,
    CTFRangeRecovery,
    CTFSpareRange,
    CTFSubmission,
    CTFTeam,
)
from ctf.services.range.recovery import get_recovery_status, recover_participant_range
from ctf.services.range.spares import create_managed_spare_user
from engine.models import Range as EngineRange
from engine.models import Request as EngineRequest
from risk_register.models import AuditLog
from shared.cloud.exceptions import CloudTaskError
from shared.enums import RangeSource, RequestType, ResourceStatus


def _make_spare_range(*, owner, scenario_id: str = "basic") -> RangeInstance:
    """Create a real, minimal CTF-sourced ``cms.RangeInstance`` + engine ``Range``/``Request``.

    The raw range object underlying a pooled spare (see
    :func:`_make_pooled_spare`) or a rebuild's old range -- the ``rebuild``
    strategy drives the real ``ctf.bridges.cms_create_range`` end to end
    instead (see module docstring), so no equivalent helper is needed for new
    ranges.
    """
    request_id = CmsRequest.objects.create(
        request_id=uuid4(), request_type=RequestType.RANGE.value, user=owner
    ).request_id
    engine_request = EngineRequest.objects.create(
        request_id=request_id, request_type=RequestType.RANGE.value, user=owner
    )
    instance_uuid = str(uuid4())
    engine_range = EngineRange.objects.create(
        uuid=uuid4(),
        user=owner,
        request=engine_request,
        cms_user_id=owner.id,
        status=EngineRange.Status.READY,
        subnet_index=EngineRange.allocate_subnet_index(),
        provisioned_instances=[
            {"uuid": instance_uuid, "role": "attacker", "os_type": "kali", "private_ip": "10.1.1.10"}
        ],
    )
    cms_request = CmsRequest.objects.get(request_id=request_id)
    range_instance = RangeInstance.objects.create(
        request=cms_request,
        scenario_id=scenario_id,
        user_id=owner.id,
        range_source=RangeSource.CTF.value,
        status=ResourceStatus.READY.value,
    )
    range_instance.engine_range = engine_range
    range_instance.instance_uuid = instance_uuid
    return range_instance


def _make_pooled_spare(
    event: CTFEvent,
    *,
    owner,
    scenario_id: str | None = None,
    status: str = SpareRangeStatus.READY.value,
) -> tuple[CTFSpareRange, RangeInstance]:
    """Create a real CTF-sourced range and register it as an available `CTFSpareRange` for `event`.

    Mirrors the row shape ``ctf.services.range.spares.provision_event_spares``
    leaves behind, without going through actual CMS provisioning dispatch.
    """
    range_instance = _make_spare_range(owner=owner, scenario_id=scenario_id or event.scenario_id)
    spare = CTFSpareRange.objects.create(
        event=event,
        owner_user=owner,
        range_instance_id=range_instance.pk,
        status=status,
    )
    return spare, range_instance


@pytest.fixture
def windows_os(db) -> OperatingSystem:
    os_obj, _ = OperatingSystem.objects.get_or_create(
        slug="windows", defaults={"name": "Windows", "extensions": [".msi"]}
    )
    return os_obj


@pytest.fixture
def participant_agent(participant_user, windows_os) -> AgentConfig:
    """A real AgentConfig owned by ``participant_user`` for scenario hydration."""
    return AgentConfig.objects.create(
        name="Recovery Test Agent",
        s3_key="agents/recovery-test/agent.msi",
        original_filename="agent.msi",
        file_size_bytes=50_000_000,
        sha256_hash="abc123",
        user=participant_user,
        os=windows_os,
    )


@pytest.fixture
def event_with_scenario(ctf_event, participant_agent):
    """CTF event configured to rebuild via the real ``basic`` scenario template.

    ``team_mode=True`` so ``rich_participant`` can validly join a team/bracket.
    """
    ctf_event.scenario_id = "basic"
    ctf_event.range_config = {"agents_by_os": {"windows": participant_agent.pk}, "ngfw_enabled": False}
    ctf_event.team_mode = True
    ctf_event.team_size_limit = 4
    ctf_event.save(update_fields=["scenario_id", "range_config", "team_mode", "team_size_limit"])
    return ctf_event


@pytest.fixture
def team_and_bracket(event_with_scenario):
    bracket = CTFBracket.objects.create(event=event_with_scenario, name="Beginner")
    team = CTFTeam.objects.create(event=event_with_scenario, name="Team Alpha")
    return team, bracket


@pytest.fixture
def rich_participant(event_with_scenario, participant_user, team_and_bracket):
    """A participant with team/bracket/submission/award/cached-score state."""
    team, bracket = team_and_bracket
    participant = CTFParticipant.objects.create(
        event=event_with_scenario,
        user=participant_user,
        email=participant_user.email,
        name="Rich Participant",
        team=team,
        bracket=bracket,
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
        cached_score=250,
        cached_solve_count=2,
    )
    old_range = _make_spare_range(owner=participant_user, scenario_id=event_with_scenario.scenario_id)
    participant.range_instance_id = old_range.pk
    participant.range_status = ResourceStatus.READY.value
    participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])
    return participant, old_range


@pytest.fixture
def submission_and_award(event_with_scenario, rich_participant, organizer_user, ctf_challenge):
    participant, _ = rich_participant
    submission = CTFSubmission.objects.create(
        participant=participant,
        challenge=ctf_challenge,
        submitted_flag="FLAG{recovered}",
        is_correct=True,
        points_awarded=ctf_challenge.points,
        attempt_number=1,
        ip_address="192.168.1.5",
    )
    award = CTFAward.objects.create(
        event=event_with_scenario,
        participant=participant,
        points=50,
        reason="Bonus for creative solution",
        granted_by=organizer_user,
    )
    return submission, award


class TestRebuildRecovery:
    """``strategy=rebuild``: provision a fresh range for the participant."""

    @pytest.mark.django_db
    def test_rebuild_preserves_identity_and_scoring_state(self, rich_participant, submission_and_award, organizer_user):
        participant, old_range = rich_participant
        submission, award = submission_and_award
        participant_pk = participant.pk
        team_id = participant.team_id
        bracket_id = participant.bracket_id
        registered_at = participant.registered_at

        result = recover_participant_range(
            participant_pk,
            strategy=RecoveryStrategy.REBUILD.value,
            operator=organizer_user,
        )

        assert result["phase"] == RecoveryPhase.COMPLETED.value
        assert result["strategy"] == RecoveryStrategy.REBUILD.value
        new_range_instance_id = result["replacement_range_instance_id"]
        assert new_range_instance_id is not None
        assert new_range_instance_id != old_range.pk

        participant.refresh_from_db()
        assert participant.pk == participant_pk
        assert participant.range_instance_id == new_range_instance_id
        assert participant.team_id == team_id
        assert participant.bracket_id == bracket_id
        assert participant.registered_at == registered_at
        assert participant.cached_score == 250
        assert participant.cached_solve_count == 2

        # Scoring rows untouched (still linked to the same, unchanged participant).
        submission.refresh_from_db()
        award.refresh_from_db()
        assert submission.participant_id == participant_pk
        assert award.participant_id == participant_pk
        assert CTFSubmission.objects.filter(participant_id=participant_pk).count() == 1
        assert CTFAward.objects.filter(participant_id=participant_pk).count() == 1

        new_instance = RangeInstance.objects.get(pk=new_range_instance_id)
        assert new_instance.user_id == participant.user_id
        assert new_instance.range_source == RangeSource.CTF.value

        recovery = CTFRangeRecovery.objects.get(participant_id=participant_pk)
        assert recovery.phase == RecoveryPhase.COMPLETED.value
        assert recovery.replacement_range_instance_id == new_range_instance_id
        assert recovery.old_range_instance_id == old_range.pk
        assert recovery.created_by_id == organizer_user.id

        audit = AuditLog.objects.get(action=AuditLog.Action.RECOVER, entity_id=old_range.pk)
        assert audit.actor_id == organizer_user.id
        assert audit.new_state["participant_id"] == str(participant_pk)
        assert audit.new_state["strategy"] == RecoveryStrategy.REBUILD.value

    @pytest.mark.django_db
    def test_old_range_access_denied_after_rebuild(self, rich_participant, organizer_user):
        from engine.services import get_rdp_connection_info

        participant, old_range = rich_participant

        recover_participant_range(
            participant.pk,
            strategy=RecoveryStrategy.REBUILD.value,
            operator=organizer_user,
        )

        old_engine_range = EngineRange.objects.get(pk=old_range.engine_range.pk)
        assert old_engine_range.status == EngineRange.Status.DESTROYING

        old_cms_instance = RangeInstance.all_objects.get(pk=old_range.pk)
        assert old_cms_instance.deleted_at is not None

        assert EngineRange.resolve_active_for_instance(participant.user, old_range.instance_uuid) is None

        # The old instance UUID never resolves again for this user -- whether
        # the replacement range has finished provisioning by assertion time
        # (-> "not found in range") or not (-> "not ready") is an environment
        # timing detail, not part of the access-denial contract being tested.
        with pytest.raises(ValueError, match=r"not found in range|not ready"):
            get_rdp_connection_info(participant.user, old_range.instance_uuid)


class TestReassignSpareRecovery:
    """``strategy=reassign_spare``: consume an event-scoped pooled spare."""

    @pytest.mark.django_db
    def test_reassign_spare_transfers_access_and_blocks_old_range(
        self, event_with_scenario, rich_participant, organizer_user
    ):
        participant, old_range = rich_participant
        spare_user = create_managed_spare_user()
        spare, spare_range = _make_pooled_spare(event_with_scenario, owner=spare_user)

        result = recover_participant_range(
            participant.pk,
            strategy=RecoveryStrategy.REASSIGN_SPARE.value,
            operator=organizer_user,
            spare_range_instance_id=spare_range.pk,
        )

        assert result["phase"] == RecoveryPhase.COMPLETED.value
        assert result["replacement_range_instance_id"] == spare_range.pk

        participant.refresh_from_db()
        assert participant.range_instance_id == spare_range.pk

        spare_instance = RangeInstance.objects.get(pk=spare_range.pk)
        assert spare_instance.user_id == participant.user_id

        spare_engine_range = EngineRange.objects.get(pk=spare_range.engine_range.pk)
        assert spare_engine_range.user_id == participant.user_id

        # New owner resolves the spare; the original (now-deleted) managed owner cannot.
        resolved = EngineRange.resolve_active_for_instance(participant.user, spare_range.instance_uuid)
        assert resolved is not None
        assert resolved.pk == spare_engine_range.pk

        # Old range is blocked for the (still the same) participant user.
        assert EngineRange.resolve_active_for_instance(participant.user, old_range.instance_uuid) is None

        spare.refresh_from_db()
        assert spare.status == SpareRangeStatus.CONSUMED.value
        assert spare.consumed_by_id == participant.pk
        assert spare.consumed_at is not None
        assert spare.owner_user_id is None

        # The freed managed spare user is deleted (best-effort cleanup).
        from django.contrib.auth.models import User

        assert not User.objects.filter(pk=spare_user.pk).exists()

        recovery = CTFRangeRecovery.objects.get(participant=participant, strategy=RecoveryStrategy.REASSIGN_SPARE.value)
        assert recovery.replacement_request_id is None

    @pytest.mark.django_db
    def test_reassign_spare_uses_live_status_when_local_status_stale(
        self, event_with_scenario, rich_participant, second_participant_user, organizer_user
    ):
        """A spare still locally ``provisioning`` is still usable once CMS reports it READY."""
        participant, _old_range = rich_participant
        _spare, spare_range = _make_pooled_spare(
            event_with_scenario,
            owner=second_participant_user,
            status=SpareRangeStatus.PROVISIONING.value,
        )
        # The underlying RangeInstance was created with status=READY (see
        # _make_spare_range) even though the pool row hasn't been synced yet.

        result = recover_participant_range(
            participant.pk,
            strategy=RecoveryStrategy.REASSIGN_SPARE.value,
            operator=organizer_user,
            spare_range_instance_id=spare_range.pk,
        )

        assert result["phase"] == RecoveryPhase.COMPLETED.value
        assert result["replacement_range_instance_id"] == spare_range.pk

    @pytest.mark.django_db
    def test_reassign_spare_excludes_already_consumed_spare(
        self, event_with_scenario, rich_participant, second_participant_user, organizer_user
    ):
        """A spare already consumed by another participant is never a candidate again."""
        participant, _old_range = rich_participant
        other_participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=second_participant_user,
            email=second_participant_user.email,
            name="Other Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        spare, _spare_range = _make_pooled_spare(event_with_scenario, owner=second_participant_user)
        spare.consumed_by = other_participant
        spare.consumed_at = timezone.now()
        spare.status = SpareRangeStatus.CONSUMED.value
        spare.save(update_fields=["consumed_by", "consumed_at", "status", "updated_at"])

        with pytest.raises(CTFRangeError, match="No compatible spare"):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REASSIGN_SPARE.value,
                operator=organizer_user,
            )

        recovery = CTFRangeRecovery.objects.get(participant=participant, strategy=RecoveryStrategy.REASSIGN_SPARE.value)
        assert recovery.phase == RecoveryPhase.FAILED.value
        assert recovery.failure_category == RecoveryFailureCategory.NO_COMPATIBLE_SPARE.value

    @pytest.mark.django_db
    def test_reassign_spare_rejects_cross_event_range(
        self, event_with_scenario, rich_participant, second_participant_user, organizer_user
    ):
        """A same-scenario spare belonging to a DIFFERENT event is never reassignable.

        Regression for the #1018 review finding: spare candidates are
        event-scoped by construction (the ``CTFSpareRange.event`` FK), so an
        organizer cannot pull another event's pooled spare into their own
        participant -- even by naming its id explicitly -- which would
        otherwise be a cross-event range takeover.
        """
        participant, _old_range = rich_participant

        other_event = CTFEvent.objects.create(
            name="Other Event",
            description="A different event sharing the scenario",
            created_by=organizer_user,
            status=EventStatus.REGISTRATION.value,
            event_start=timezone.now() + timedelta(days=1),
            event_end=timezone.now() + timedelta(days=1, hours=8),
            scenario_id=event_with_scenario.scenario_id,
            auto_cleanup=True,
            cleanup_delay_hours=24,
            team_mode=False,
        )
        _foreign_spare, foreign_spare_range = _make_pooled_spare(other_event, owner=second_participant_user)

        # Even naming the foreign spare explicitly must be refused.
        with pytest.raises(CTFRangeError, match="No compatible spare"):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REASSIGN_SPARE.value,
                operator=organizer_user,
                spare_range_instance_id=foreign_spare_range.pk,
            )

        # The foreign range's ownership is untouched.
        foreign_spare_range.refresh_from_db()
        assert foreign_spare_range.user_id == second_participant_user.id


class TestRebuildFallbackWhenPoolEmpty:
    """An operator can retry with ``rebuild`` after ``reassign_spare`` fails on an empty pool."""

    @pytest.mark.django_db
    def test_rebuild_succeeds_after_reassign_spare_fails_with_empty_pool(
        self, event_with_scenario, rich_participant, organizer_user
    ):
        participant, old_range = rich_participant
        assert not CTFSpareRange.objects.filter(event=event_with_scenario).exists()

        with pytest.raises(CTFRangeError, match="No compatible spare"):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REASSIGN_SPARE.value,
                operator=organizer_user,
            )

        failed_recovery = CTFRangeRecovery.objects.get(
            participant=participant, strategy=RecoveryStrategy.REASSIGN_SPARE.value
        )
        assert failed_recovery.phase == RecoveryPhase.FAILED.value

        # A distinct intent record (strategy is part of the unique key) lets the
        # operator retry the SAME old range with a different strategy.
        result = recover_participant_range(
            participant.pk,
            strategy=RecoveryStrategy.REBUILD.value,
            operator=organizer_user,
        )

        assert result["phase"] == RecoveryPhase.COMPLETED.value
        assert result["replacement_range_instance_id"] is not None
        assert result["replacement_range_instance_id"] != old_range.pk

        rebuild_recovery = CTFRangeRecovery.objects.get(
            participant=participant, strategy=RecoveryStrategy.REBUILD.value
        )
        assert rebuild_recovery.phase == RecoveryPhase.COMPLETED.value
        assert CTFRangeRecovery.objects.filter(participant=participant).count() == 2

        participant.refresh_from_db()
        assert participant.range_instance_id == result["replacement_range_instance_id"]


class TestIdempotentRetry:
    """Retrying after a checkpointed-phase failure resumes without duplicating work.

    Uses ``reassign_spare`` (not ``rebuild``): its replacement step runs
    *before* old-range teardown (see ``ctf.services.range.recovery`` module
    docstring), so injecting the failure at teardown exercises retry *after*
    the replacement already exists -- proving a second reassignment is not
    attempted and no second audit row is written.
    """

    @pytest.mark.django_db
    def test_retry_after_teardown_failure_resumes_without_duplicating(
        self, monkeypatch, event_with_scenario, rich_participant, second_participant_user, organizer_user
    ):
        participant, old_range = rich_participant
        _spare, spare_range = _make_pooled_spare(event_with_scenario, owner=second_participant_user)
        call_count = {"n": 0}

        def flaky_teardown(request_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise CloudTaskError("simulated transient ECS failure")
            return None

        monkeypatch.setattr("engine.ecs.start_range_teardown", flaky_teardown)

        with pytest.raises(CTFRangeError):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REASSIGN_SPARE.value,
                operator=organizer_user,
                spare_range_instance_id=spare_range.pk,
            )

        recovery = CTFRangeRecovery.objects.get(participant=participant)
        assert recovery.phase == RecoveryPhase.FAILED.value
        assert recovery.failure_category == RecoveryFailureCategory.OLD_RANGE_TEARDOWN_FAILED.value
        # The spare was already reassigned before teardown failed.
        assert recovery.replacement_range_instance_id == spare_range.pk
        assert RangeInstance.objects.get(pk=spare_range.pk).user_id == participant.user_id

        # Retry: same call resumes and completes without re-reassigning the spare.
        result = recover_participant_range(
            participant.pk,
            strategy=RecoveryStrategy.REASSIGN_SPARE.value,
            operator=organizer_user,
            spare_range_instance_id=spare_range.pk,
        )

        assert result["phase"] == RecoveryPhase.COMPLETED.value
        assert result["replacement_range_instance_id"] == spare_range.pk
        assert call_count["n"] == 2
        # No duplicate recovery record or audit row from the retry.
        assert CTFRangeRecovery.objects.filter(participant=participant).count() == 1
        assert AuditLog.objects.filter(action=AuditLog.Action.RECOVER, entity_id=old_range.pk).count() == 1

        participant.refresh_from_db()
        assert participant.range_instance_id == spare_range.pk


class TestValidationAndFailures:
    @pytest.mark.django_db
    def test_participant_not_found(self, organizer_user):
        with pytest.raises(CTFNotFoundError):
            recover_participant_range(
                uuid4(),
                strategy=RecoveryStrategy.REBUILD.value,
                operator=organizer_user,
            )

    @pytest.mark.django_db
    def test_invalid_strategy(self, rich_participant, organizer_user):
        participant, _ = rich_participant
        with pytest.raises(CTFValidationError):
            recover_participant_range(
                participant.pk,
                strategy="not_a_real_strategy",
                operator=organizer_user,
            )
        assert not CTFRangeRecovery.objects.filter(participant=participant).exists()

    @pytest.mark.django_db
    def test_unregistered_participant_rejected(self, event_with_scenario, organizer_user):
        participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=None,
            email="unregistered@test.com",
            name="Unregistered",
            status=ParticipantStatus.INVITED.value,
            invite_token="recovery-test-token",
            invite_token_expires=timezone.now() + timedelta(days=7),
        )
        with pytest.raises(CTFValidationError, match="registered"):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REBUILD.value,
                operator=organizer_user,
            )

    @pytest.mark.django_db
    def test_participant_with_no_range_rejected(self, event_with_scenario, participant_user, organizer_user):
        participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=participant_user,
            email=participant_user.email,
            name="No Range Participant",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=timezone.now(),
        )
        with pytest.raises(CTFRangeError, match="no range"):
            recover_participant_range(
                participant.pk,
                strategy=RecoveryStrategy.REBUILD.value,
                operator=organizer_user,
            )


class TestGetRecoveryStatus:
    @pytest.mark.django_db
    def test_returns_none_when_no_recovery_exists(self, rich_participant):
        participant, _ = rich_participant
        assert get_recovery_status(participant.pk) is None

    @pytest.mark.django_db
    def test_returns_latest_recovery_after_completion(self, rich_participant, organizer_user):
        participant, _ = rich_participant

        recover_participant_range(
            participant.pk,
            strategy=RecoveryStrategy.REBUILD.value,
            operator=organizer_user,
        )

        status = get_recovery_status(participant.pk)
        assert status is not None
        assert status["phase"] == RecoveryPhase.COMPLETED.value
        assert status["strategy"] == RecoveryStrategy.REBUILD.value
        assert status["replacement_range_instance_id"] is not None
