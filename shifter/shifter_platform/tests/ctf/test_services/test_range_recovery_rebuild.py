"""CTF participant-range recovery: the ``rebuild`` strategy (issue #1018).

Split from ``test_range_recovery`` by behavior; shares its fixtures and the same
boundary-mock policy (real CMS/Engine creation and teardown stacks, cloud
dispatch held at its seam).
"""

from __future__ import annotations

import pytest

from cms.models import RangeInstance
from ctf.enums import RecoveryPhase, RecoveryStrategy
from ctf.models import CTFAward, CTFRangeRecovery, CTFSubmission
from ctf.services.range.recovery import recover_participant_range
from engine.models import Range as EngineRange
from shared.audit import AuditAction
from shared.enums import RangeSource, ResourceStatus
from shared.models import AuditLog
from tests.ctf.test_services.test_range_recovery import event_with_scenario as event_with_scenario
from tests.ctf.test_services.test_range_recovery import rich_participant as rich_participant
from tests.ctf.test_services.test_range_recovery import team_and_bracket as team_and_bracket


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
    @pytest.mark.parametrize("old_range_status", [ResourceStatus.READY.value, ResourceStatus.FAILED.value])
    def test_rebuild_admits_against_realized_range_subject_not_draw(
        self, rich_participant, organizer_user, monkeypatch, old_range_status
    ):
        # PLAT-202 (#2119): the replacement must be admitted against the realized
        # range's membership subject, not the draw — else a binding published
        # against the range would be silently dropped on rebuild. A FAILED range is
        # the organizer's main reason to rebuild and must hand over its identity
        # too, though its CMS instance is already soft-deleted (#2462).
        import cms.services._model_admission as gate
        from shared.model_access import OwnedReference

        participant, old_range = rich_participant
        if old_range_status == ResourceStatus.FAILED.value:
            EngineRange.objects.filter(pk=old_range.engine_range.pk).update(status=EngineRange.Status.FAILED)
            old_range.status = old_range_status
            old_range.save(update_fields=["status"])
            participant.range_status = old_range_status
            participant.save(update_fields=["range_status", "updated_at"])
        captured: dict[str, object] = {}
        original = gate.assert_launch_model_access

        def _spy(**kwargs):
            captured["subject"] = kwargs.get("subject")
            return original(**kwargs)

        monkeypatch.setattr(gate, "assert_launch_model_access", _spy)

        result = recover_participant_range(
            participant.pk, strategy=RecoveryStrategy.REBUILD.value, operator=organizer_user
        )

        assert result["phase"] == RecoveryPhase.COMPLETED.value
        assert captured["subject"] == OwnedReference(
            owner="deployment", reference=f"range:{old_range.engine_range.uuid}"
        )

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

        audit = AuditLog.objects.get(action=AuditAction.RECOVER, entity_id=old_range.pk)
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
