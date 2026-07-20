"""CTF bookkeeping projections for shared range-lease teardown (#1696)."""

from __future__ import annotations

import pytest

from cms.signals import range_status_changed
from ctf.enums import ParticipantStatus
from ctf.models import CTFParticipant
from shared.enums import ResourceStatus

pytestmark = pytest.mark.django_db


def test_destroyed_lease_range_clears_participant_range_reference(ctf_event, participant_user):
    participant = CTFParticipant.objects.create(
        event=ctf_event,
        user=participant_user,
        email=participant_user.email,
        name="Lease Participant",
        status=ParticipantStatus.ACTIVE.value,
        range_instance_id=1234,
        range_status=ResourceStatus.DESTROYING.value,
    )

    range_status_changed.send(
        sender=None,
        range_instance_id=1234,
        new_status=ResourceStatus.DESTROYED.value,
        previous_status=ResourceStatus.DESTROYING.value,
    )

    participant.refresh_from_db()
    assert participant.range_instance_id is None
    assert participant.range_status == ""


def test_nonterminal_lease_status_still_updates_participant_projection(ctf_event, participant_user):
    participant = CTFParticipant.objects.create(
        event=ctf_event,
        user=participant_user,
        email=participant_user.email,
        name="Lease Participant",
        status=ParticipantStatus.ACTIVE.value,
        range_instance_id=5678,
        range_status=ResourceStatus.PROVISIONING.value,
    )

    range_status_changed.send(
        sender=None,
        range_instance_id=5678,
        new_status=ResourceStatus.READY.value,
        previous_status=ResourceStatus.PROVISIONING.value,
    )

    participant.refresh_from_db()
    assert participant.range_instance_id == 5678
    assert participant.range_status == ResourceStatus.READY.value
