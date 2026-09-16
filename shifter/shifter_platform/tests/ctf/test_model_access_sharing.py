"""CTF-owned model-access selector resolution."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from ctf.enums import ParticipantStatus, SpareRangeStatus
from ctf.models import CTFCohort, CTFParticipant, CTFSpareRange, CTFTeam
from ctf.services import ModelAccessSelectorError, resolve_model_access_selector
from engine.services import ModelAccessRangeView
from shared.model_access import OwnedReference, SelectorKind, SharingSelector

pytestmark = pytest.mark.django_db


def _range_view(instance_id: int) -> ModelAccessRangeView:
    range_uuid = UUID(int=instance_id)
    return ModelAccessRangeView(
        range_ref=OwnedReference(owner="deployment", reference=f"range:{range_uuid}"),
        authority_ref=OwnedReference(owner="engine", reference=f"range:{range_uuid}"),
        range_uuid=range_uuid,
        owner_user_id=instance_id,
        workspace_id=1,
    )


def test_event_team_and_cohort_resolve_realized_and_stable_draw_members(
    ctf_event_team,
    organizer_user,
    monkeypatch,
):
    team = CTFTeam.objects.create(event=ctf_event_team, name="Alpha")
    cohort = CTFCohort.objects.create(event=ctf_event_team, name="Morning")
    participant = CTFParticipant.objects.create(
        event=ctf_event_team,
        name="Player",
        email="player@example.test",
        status=ParticipantStatus.REGISTERED.value,
        registered_at=timezone.now(),
        team=team,
        cohort=cohort,
        range_instance_id=101,
    )
    waiting = CTFParticipant.objects.create(
        event=ctf_event_team,
        name="Waiting",
        email="waiting@example.test",
        status=ParticipantStatus.REGISTERED.value,
        registered_at=timezone.now(),
    )
    assigned_spare = CTFSpareRange.objects.create(
        event=ctf_event_team,
        team=team,
        cohort=cohort,
        range_instance_id=102,
        status=SpareRangeStatus.READY.value,
    )
    event_spare = CTFSpareRange.objects.create(
        event=ctf_event_team,
        status=SpareRangeStatus.PROVISIONING.value,
    )

    def resolve_instances(instance_ids):
        return tuple(_range_view(instance_id) for instance_id in instance_ids)

    monkeypatch.setattr("ctf.bridges.cms_resolve_model_access_range_instances", resolve_instances)

    event_resolution = resolve_model_access_selector(
        organizer_user,
        SharingSelector(
            kind=SelectorKind.CTF_EVENT,
            ids=(str(ctf_event_team.pk),),
            include_spares=True,
        ),
    )
    assert len(event_resolution.member_refs) == 4
    assert OwnedReference(owner="ctf", reference=f"draw:{waiting.pk}") in event_resolution.member_refs
    assert OwnedReference(owner="ctf", reference=f"draw:{event_spare.pk}") in event_resolution.member_refs

    team_resolution = resolve_model_access_selector(
        organizer_user,
        SharingSelector(kind=SelectorKind.CTF_TEAM, ids=(str(team.pk),), include_spares=True),
    )
    assert {item.reference for item in team_resolution.member_refs} == {
        f"range:{UUID(int=101)}",
        f"range:{UUID(int=102)}",
    }
    assert team_resolution.selector_authority_refs == (OwnedReference(owner="ctf", reference=f"team:{team.pk}"),)

    cohort_resolution = resolve_model_access_selector(
        organizer_user,
        SharingSelector(kind=SelectorKind.CTF_COHORT, ids=(str(cohort.pk),), include_spares=True),
    )
    assert {item.reference for item in cohort_resolution.member_refs} == {
        f"range:{UUID(int=101)}",
        f"range:{UUID(int=102)}",
    }
    assert participant.pk
    assert assigned_spare.pk


def test_ctf_selector_denies_unknown_and_cross_event_organizer(ctf_event, organizer_user, django_user_model):
    outsider = django_user_model.objects.create_user("other-organizer@example.test")
    for actor, event_id in ((organizer_user, uuid4()), (outsider, ctf_event.pk)):
        with pytest.raises(ModelAccessSelectorError):
            resolve_model_access_selector(
                actor,
                SharingSelector(kind=SelectorKind.CTF_EVENT, ids=(str(event_id),)),
            )


def test_participant_membership_mutation_invalidates_old_and_new_owner_refs(
    ctf_event_team,
    monkeypatch,
):
    old_team = CTFTeam.objects.create(event=ctf_event_team, name="Old")
    new_team = CTFTeam.objects.create(event=ctf_event_team, name="New")
    participant = CTFParticipant.objects.create(
        event=ctf_event_team,
        name="Mover",
        email="mover@example.test",
        status=ParticipantStatus.REGISTERED.value,
        registered_at=timezone.now(),
        team=old_team,
    )
    commands = []
    monkeypatch.setattr(
        "ctf.bridges.cms_invalidate_model_access_authority",
        lambda command: commands.append(command) or 1,
    )

    participant.team = new_team
    participant.save(update_fields=["team", "updated_at"])

    references = {(item.owner, item.reference) for command in commands for item in command.authority_refs}
    assert ("ctf", f"event:{ctf_event_team.pk}") in references
    assert ("ctf", f"team:{old_team.pk}") in references
    assert ("ctf", f"team:{new_team.pk}") in references
    assert ("ctf", f"participant:{participant.pk}") in references


def test_organizer_can_select_explicit_ctf_range_but_not_foreign_ctf_range(
    ctf_event,
    organizer_user,
    django_user_model,
    monkeypatch,
):
    participant = CTFParticipant.objects.create(
        event=ctf_event,
        name="Selected",
        email="selected@example.test",
        status=ParticipantStatus.REGISTERED.value,
        registered_at=timezone.now(),
        range_instance_id=303,
    )
    range_view = _range_view(303)
    monkeypatch.setattr(
        "ctf.bridges.cms_resolve_model_access_selected_ranges",
        lambda range_uuids: (SimpleNamespace(range_instance_id=303, range_view=range_view),),
        raising=False,
    )
    selector = SharingSelector(
        kind=SelectorKind.SELECTED_RANGES,
        ids=(str(range_view.range_uuid),),
    )

    resolution = resolve_model_access_selector(organizer_user, selector)
    assert resolution.member_refs == (range_view.range_ref,)
    assert resolution.subject_authorities[0].authority_ref == OwnedReference(
        owner="ctf",
        reference=f"participant:{participant.pk}",
    )

    outsider = django_user_model.objects.create_user("foreign-organizer@example.test")
    with pytest.raises(ModelAccessSelectorError):
        resolve_model_access_selector(outsider, selector)
