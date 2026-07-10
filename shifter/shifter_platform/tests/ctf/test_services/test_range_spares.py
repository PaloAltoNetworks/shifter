"""Tests for the CTF event spare-range pool (issue #1018 revised plan).

DB-backed integration-style tests (per the repo's OOM lesson: fixtures and
real rows over many micro-tests with inline mocks). Per ADR-019's
boundary-mock policy, ``provision_event_spares`` drives the real
``ctf.bridges.cms_create_range`` -> ``cms.services.create_range`` ->
``engine.services.create_range`` stack (engine ECS is unconfigured in test
settings, so provisioning dispatch is a no-op -- see
``tests/cms/test_services_range.py`` and
``tests/ctf/test_services/test_range_recovery.py``), so a provisioned spare's
``range_instance_id`` resolves synchronously exactly as it does in production.

The scenario used here is deliberately **agent-free** (``xdr_agent: False``
on every instance -- see ``cms.scenarios.schema.ScenarioTemplate.get_agent_requirements``),
unlike ``test_range_recovery.py``'s ``basic`` scenario. Each pooled spare is
provisioned under its own freshly created managed user
(:func:`ctf.services.range.spares.create_managed_spare_user`), and
``cms.services._agents.get_agent`` enforces strict per-user agent ownership,
so a shared ``agents_by_os`` agent (owned by one fixture user) could never be
resolved for many distinct spare-owning users. Avoiding the agent
requirement entirely keeps this file focused on spare-pool bookkeeping.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User

from cms.models import RangeInstance, Scenario
from ctf.enums import ParticipantStatus, SpareRangeStatus
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFParticipant, CTFSpareRange
from ctf.services.range.spares import (
    cleanup_event_spares,
    create_managed_spare_user,
    delete_managed_spare_user,
    get_event_spare_summary,
    provision_event_spares,
)
from risk_register.models import AuditLog

_NO_AGENT_SCENARIO_DEFINITION = {
    "instances": [
        {"name": "Attacker", "role": "attacker", "os_type": "kali", "xdr_agent": False},
        {"name": "Target", "role": "victim", "os_type": "windows", "xdr_agent": False},
    ],
    "subnets": [{"name": "core", "instances": ["Attacker", "Target"]}],
    "ngfw": False,
}


@pytest.fixture
def spare_pool_scenario(organizer_user) -> Scenario:
    """An agent-free scenario so provisioning succeeds under any managed spare user."""
    return Scenario.objects.create(
        scenario_id="ctf-spare-pool-test",
        name="CTF Spare Pool Test Range",
        description="Agent-free hydratable scenario for spare-pool provisioning tests.",
        definition=_NO_AGENT_SCENARIO_DEFINITION,
        created_by=organizer_user,
        updated_by=organizer_user,
    )


@pytest.fixture
def event_with_scenario(ctf_event, spare_pool_scenario) -> CTFEvent:
    """CTF event configured so spares can be built via the agent-free test scenario."""
    ctf_event.scenario_id = spare_pool_scenario.scenario_id
    ctf_event.range_config = {"agents_by_os": {}, "ngfw_enabled": False}
    ctf_event.save(update_fields=["scenario_id", "range_config"])
    return ctf_event


class TestManagedSpareUser:
    @pytest.mark.django_db
    def test_create_managed_spare_user_is_inactive_and_marked(self):
        user = create_managed_spare_user()

        assert user.is_active is False
        assert user.has_usable_password() is False
        assert user.email.endswith("@ctf-spare.invalid")
        assert user.username.startswith("ctf-spare-")
        assert not CTFParticipant.objects.filter(user=user).exists()

    @pytest.mark.django_db
    def test_delete_managed_spare_user_deletes_marked_user(self):
        user = create_managed_spare_user()
        user_pk = user.pk

        assert delete_managed_spare_user(user) is True
        assert not User.objects.filter(pk=user_pk).exists()

    @pytest.mark.django_db
    def test_delete_managed_spare_user_refuses_non_spare_user(self, organizer_user):
        """A real (non-``@ctf-spare.invalid``) user is never deleted, even if passed in by mistake."""
        assert delete_managed_spare_user(organizer_user) is False
        assert User.objects.filter(pk=organizer_user.pk).exists()

    def test_delete_managed_spare_user_none_is_a_safe_no_op(self):
        assert delete_managed_spare_user(None) is False


class TestProvisionEventSpares:
    @pytest.mark.django_db
    def test_creates_managed_user_owned_rows(self, event_with_scenario, organizer_user):
        result = provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)

        assert result == {
            "event_id": str(event_with_scenario.pk),
            "target_count": 2,
            "existing": 0,
            "created": 2,
        }

        event_with_scenario.refresh_from_db()
        assert event_with_scenario.spare_range_count == 2

        spares = list(CTFSpareRange.objects.filter(event=event_with_scenario))
        assert len(spares) == 2
        for spare in spares:
            assert spare.range_instance_id is not None
            assert spare.status == SpareRangeStatus.PROVISIONING.value
            assert spare.owner_user is not None
            assert spare.owner_user.is_active is False
            assert spare.owner_user.email.endswith("@ctf-spare.invalid")
            # Never a CTFParticipant -- excluded from participant/scoreboard surfaces.
            assert not CTFParticipant.objects.filter(user=spare.owner_user).exists()
            instance = RangeInstance.objects.get(pk=spare.range_instance_id)
            assert instance.user_id == spare.owner_user_id

        audit = AuditLog.objects.get(action=AuditLog.Action.SPARE_PROVISION)
        assert audit.actor_id == organizer_user.id
        assert audit.new_state["event_id"] == str(event_with_scenario.pk)
        assert audit.new_state["created"] == 2

    @pytest.mark.django_db
    def test_top_up_is_idempotent_at_the_same_target(self, event_with_scenario, organizer_user):
        provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)
        first_ids = set(CTFSpareRange.objects.filter(event=event_with_scenario).values_list("pk", flat=True))

        result = provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)

        assert result["existing"] == 2
        assert result["created"] == 0
        second_ids = set(CTFSpareRange.objects.filter(event=event_with_scenario).values_list("pk", flat=True))
        assert first_ids == second_ids

    @pytest.mark.django_db
    def test_top_up_increases_pool_to_new_target(self, event_with_scenario, organizer_user):
        provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)

        result = provision_event_spares(event_with_scenario.pk, 5, operator=organizer_user)

        assert result["existing"] == 2
        assert result["created"] == 3
        assert CTFSpareRange.objects.filter(event=event_with_scenario).count() == 5
        event_with_scenario.refresh_from_db()
        assert event_with_scenario.spare_range_count == 5

    @pytest.mark.django_db
    def test_top_up_replaces_failed_and_consumed_spares(self, event_with_scenario, organizer_user, participant_user):
        provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)
        spares = list(CTFSpareRange.objects.filter(event=event_with_scenario))
        spares[0].status = SpareRangeStatus.FAILED.value
        spares[0].save(update_fields=["status", "updated_at"])
        participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=participant_user,
            email=participant_user.email,
            name="Consumer",
            status=ParticipantStatus.ACTIVE.value,
        )
        spares[1].consumed_by = participant
        spares[1].status = SpareRangeStatus.CONSUMED.value
        spares[1].save(update_fields=["consumed_by", "status", "updated_at"])

        result = provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)

        # Both existing rows are failed/consumed, so "existing" (active) is 0
        # and a fresh top-up to 2 creates 2 new spares.
        assert result["existing"] == 0
        assert result["created"] == 2
        assert CTFSpareRange.objects.filter(event=event_with_scenario).count() == 4

    @pytest.mark.django_db
    def test_event_not_found_raises(self):
        import uuid

        with pytest.raises(CTFNotFoundError):
            provision_event_spares(uuid.uuid4(), 1)

    @pytest.mark.django_db
    def test_a_spares_provisioning_failure_is_recorded_failed_and_topup_continues(self, ctf_event, organizer_user):
        """A real (unmocked) hydration failure -- a scenario_id CMS has never heard
        of -- drives ``_provision_one_spare``'s ``except Exception`` branch for
        every attempt in the top-up. Each failure is recorded as a ``failed``
        ``CTFSpareRange`` rather than raised, so the loop still makes all
        ``to_create`` attempts instead of aborting after the first one.
        """
        ctf_event.scenario_id = "no-such-scenario-1018"
        ctf_event.range_config = {"agents_by_os": {}, "ngfw_enabled": False}
        ctf_event.save(update_fields=["scenario_id", "range_config"])

        result = provision_event_spares(ctf_event.pk, 3, operator=organizer_user)

        # Failures are never counted as "created" ...
        assert result["created"] == 0
        # ... but the loop still ran all 3 attempts rather than stopping after
        # the first failure.
        spares = list(CTFSpareRange.objects.filter(event=ctf_event))
        assert len(spares) == 3
        for spare in spares:
            assert spare.status == SpareRangeStatus.FAILED.value
            assert spare.range_instance_id is None
            # The managed spare user is still created before the provisioning
            # attempt fails.
            assert spare.owner_user is not None
            assert spare.owner_user.email.endswith("@ctf-spare.invalid")


class TestGetEventSpareSummary:
    @pytest.mark.django_db
    def test_counts_by_status_and_available(self, event_with_scenario, organizer_user, participant_user):
        provision_event_spares(event_with_scenario.pk, 3, operator=organizer_user)
        spares = list(CTFSpareRange.objects.filter(event=event_with_scenario))
        spares[0].status = SpareRangeStatus.READY.value
        spares[0].save(update_fields=["status", "updated_at"])
        spares[1].status = SpareRangeStatus.FAILED.value
        spares[1].save(update_fields=["status", "updated_at"])
        # spares[2] stays "provisioning".

        summary = get_event_spare_summary(event_with_scenario.pk)

        assert summary["event_id"] == str(event_with_scenario.pk)
        assert summary["target_count"] == 3
        assert summary["counts"][SpareRangeStatus.READY.value] == 1
        assert summary["counts"][SpareRangeStatus.FAILED.value] == 1
        assert summary["counts"][SpareRangeStatus.PROVISIONING.value] == 1
        assert summary["counts"][SpareRangeStatus.CONSUMED.value] == 0
        assert summary["available"] == 1

    @pytest.mark.django_db
    def test_event_not_found_raises(self):
        import uuid

        with pytest.raises(CTFNotFoundError):
            get_event_spare_summary(uuid.uuid4())


class TestSpareStatusSignalSync:
    """``ctf.signals.sync_ctf_spare_range_status`` is the "existing event projection"

    that moves a pooled spare from ``provisioning`` to ``ready``/``failed`` -- the
    same ``cms.services.range_status_changed`` signal that already syncs
    ``CTFParticipant.range_status`` (see ``sync_ctf_participant_range_status``).
    """

    @pytest.mark.django_db
    def test_ready_status_change_syncs_unconsumed_spare(self, event_with_scenario, organizer_user):
        from cms.signals import range_status_changed
        from shared.enums import ResourceStatus

        provision_event_spares(event_with_scenario.pk, 1, operator=organizer_user)
        spare = CTFSpareRange.objects.get(event=event_with_scenario)
        assert spare.status == SpareRangeStatus.PROVISIONING.value

        range_status_changed.send(
            sender=None,
            range_instance_id=spare.range_instance_id,
            new_status=ResourceStatus.READY.value,
            previous_status=ResourceStatus.PROVISIONING.value,
        )

        spare.refresh_from_db()
        assert spare.status == SpareRangeStatus.READY.value

    @pytest.mark.django_db
    def test_unmapped_status_change_is_a_no_op(self, event_with_scenario, organizer_user):
        """A CMS status with no spare-pool projection (e.g. ``provisioning`` ->
        ``provisioning``, or any status other than ``ready``/``failed``) hits the
        early-return branch: the signal is a no-op rather than raising or
        touching the spare row.
        """
        from cms.signals import range_status_changed
        from shared.enums import ResourceStatus

        provision_event_spares(event_with_scenario.pk, 1, operator=organizer_user)
        spare = CTFSpareRange.objects.get(event=event_with_scenario)
        assert spare.status == SpareRangeStatus.PROVISIONING.value

        range_status_changed.send(
            sender=None,
            range_instance_id=spare.range_instance_id,
            new_status=ResourceStatus.PAUSED.value,
            previous_status=ResourceStatus.READY.value,
        )

        spare.refresh_from_db()
        assert spare.status == SpareRangeStatus.PROVISIONING.value

    @pytest.mark.django_db
    def test_status_change_never_touches_a_consumed_spare(self, event_with_scenario, organizer_user, participant_user):
        from cms.signals import range_status_changed
        from shared.enums import ResourceStatus

        provision_event_spares(event_with_scenario.pk, 1, operator=organizer_user)
        spare = CTFSpareRange.objects.get(event=event_with_scenario)
        participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=participant_user,
            email=participant_user.email,
            name="Consumer",
            status=ParticipantStatus.ACTIVE.value,
        )
        spare.consumed_by = participant
        spare.status = SpareRangeStatus.CONSUMED.value
        spare.save(update_fields=["consumed_by", "status", "updated_at"])

        range_status_changed.send(
            sender=None,
            range_instance_id=spare.range_instance_id,
            new_status=ResourceStatus.FAILED.value,
            previous_status=ResourceStatus.READY.value,
        )

        spare.refresh_from_db()
        assert spare.status == SpareRangeStatus.CONSUMED.value


class TestCleanupEventSpares:
    @pytest.mark.django_db
    def test_tears_down_unconsumed_spares_and_deletes_users(self, event_with_scenario, organizer_user):
        provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)
        spares = list(CTFSpareRange.objects.filter(event=event_with_scenario))
        owner_ids = [s.owner_user_id for s in spares]
        range_ids = [s.range_instance_id for s in spares]

        result = cleanup_event_spares(event_with_scenario.pk)

        assert result["destroyed"] == 2
        assert result["users_deleted"] == 2
        assert result["failed"] == 0

        for range_id in range_ids:
            # The underlying local dev provisioner subprocess may complete
            # teardown (hard-removing the row) before this assertion runs, or
            # may not have yet (leaving it soft-deleted) -- an environment
            # timing detail, not part of the "torn down" contract being
            # tested (see the same reasoning in
            # test_range_recovery.py::test_old_range_access_denied_after_rebuild).
            instance = RangeInstance.all_objects.filter(pk=range_id).first()
            assert instance is None or instance.deleted_at is not None
        for owner_id in owner_ids:
            assert not User.objects.filter(pk=owner_id).exists()
        for spare in CTFSpareRange.objects.filter(event=event_with_scenario):
            assert spare.owner_user_id is None

    @pytest.mark.django_db
    def test_a_single_spares_destroy_failure_is_counted_without_aborting_the_others(
        self, event_with_scenario, organizer_user
    ):
        """One spare's underlying ``RangeInstance`` is hard-deleted out from under it
        (a real, unmocked way to make ``cms_destroy_range`` genuinely raise
        ``CMSError`` -- "range not found" -- for that spare only), so the loop's
        ``except Exception`` branch is exercised for real. The other spare must
        still be destroyed and both managed users still cleaned up.
        """
        provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)
        spares = list(CTFSpareRange.objects.filter(event=event_with_scenario))
        owner_ids = [s.owner_user_id for s in spares]
        doomed_range_id = spares[0].range_instance_id
        RangeInstance.all_objects.filter(pk=doomed_range_id).delete()

        result = cleanup_event_spares(event_with_scenario.pk)

        assert result["destroyed"] == 1
        assert result["failed"] == 1
        # Both managed users are freed regardless of whether their range's
        # destroy call succeeded.
        assert result["users_deleted"] == 2
        for owner_id in owner_ids:
            assert not User.objects.filter(pk=owner_id).exists()
        for spare in CTFSpareRange.objects.filter(event=event_with_scenario):
            assert spare.status == SpareRangeStatus.FAILED.value
            assert spare.owner_user_id is None

    @pytest.mark.django_db
    def test_leaves_consumed_spares_alone(self, event_with_scenario, organizer_user, participant_user):
        provision_event_spares(event_with_scenario.pk, 1, operator=organizer_user)
        spare = CTFSpareRange.objects.get(event=event_with_scenario)
        owner_id = spare.owner_user_id
        participant = CTFParticipant.objects.create(
            event=event_with_scenario,
            user=participant_user,
            email=participant_user.email,
            name="Consumer",
            status=ParticipantStatus.ACTIVE.value,
        )
        spare.consumed_by = participant
        spare.status = SpareRangeStatus.CONSUMED.value
        spare.save(update_fields=["consumed_by", "status", "updated_at"])

        result = cleanup_event_spares(event_with_scenario.pk)

        assert result["destroyed"] == 0
        assert result["users_deleted"] == 0
        spare.refresh_from_db()
        assert spare.status == SpareRangeStatus.CONSUMED.value
        assert spare.owner_user_id == owner_id

    @pytest.mark.django_db
    def test_event_not_found_raises(self):
        import uuid

        with pytest.raises(CTFNotFoundError):
            cleanup_event_spares(uuid.uuid4())


class TestCleanupEventRangesWiresSpares:
    """``cleanup_event_ranges`` (event teardown entry point) also tears down the
    event's spare pool, end to end through the real service (#1018)."""

    @pytest.mark.django_db
    def test_cleanup_event_ranges_tears_down_unconsumed_spares(self, event_with_scenario, organizer_user):
        from ctf.services.range import cleanup_event_ranges

        provision_event_spares(event_with_scenario.pk, 2, operator=organizer_user)
        spares = list(CTFSpareRange.objects.filter(event=event_with_scenario))
        owner_ids = [s.owner_user_id for s in spares]

        cleanup_event_ranges(event_with_scenario.pk)

        for owner_id in owner_ids:
            assert not User.objects.filter(pk=owner_id).exists()
        for spare in CTFSpareRange.objects.filter(event=event_with_scenario):
            assert spare.status == SpareRangeStatus.FAILED.value
            assert spare.owner_user_id is None


class TestCleanupEventSparesBestEffort:
    """``_cleanup_event_spares_best_effort`` (issue #1018): a spare-cleanup failure
    must never abort the participant-range cleanup ``cleanup_event_ranges`` runs it
    after.

    Exercises the real, unmocked failure path -- ``cleanup_event_spares`` raising a
    genuine ``CTFNotFoundError`` for a nonexistent event -- rather than mocking a
    first-party target, per ADR-019's boundary-mock policy (the legacy
    ``boundary_mock_baseline.json`` ratchet only shrinks; it does not admit new
    first-party patch targets).
    """

    @pytest.mark.django_db
    def test_swallows_a_real_cleanup_failure_without_raising(self):
        import uuid

        from ctf.services.range.lifecycle import _cleanup_event_spares_best_effort

        # No event exists for this id, so the real `cleanup_event_spares` call
        # inside genuinely raises `CTFNotFoundError`; the wrapper must swallow it
        # rather than let it propagate.
        _cleanup_event_spares_best_effort(uuid.uuid4())
