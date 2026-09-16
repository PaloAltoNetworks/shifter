"""Admission backpressure: fan-out, fixed-window rate, and durable outstanding-work.

Covers issue #2098 (CTF-008) admission controls wired into ``release_campaign``:
a rejected request fails closed with a bounded error and never partially admits,
and a replay never double-reserves capacity.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.utils import timezone

import workspaces.services as workspace_services
from ctf.enums import ParticipantStatus
from ctf.exceptions import CTFCommunicationError
from ctf.models import CTFParticipant, DeliveryAttempt
from ctf.services.communication import CampaignDraft, create_campaign, release_campaign

pytestmark = pytest.mark.django_db


class _NullPublisher:
    """A put_metric_data-compatible sink so denial metrics run real logic off the cloud."""

    def put_metric_data(self, **kwargs: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _hermetic_metrics(monkeypatch):
    """Keep admission-denial metrics off the real cloud (ADR-019: mock the transport)."""
    monkeypatch.setattr("ctf.services.communication.metrics._resolve_client", lambda: _NullPublisher())


@pytest.fixture(autouse=True)
def _clear_rate_cache():
    """Clear the process-global locmem cache so fixed-window counters do not leak across tests."""
    cache.clear()
    yield
    cache.clear()


def _workspace_uuid(user):
    return str(workspace_services.resolve_personal_workspace(user).workspace_uuid)


def _participant(event, email):
    return CTFParticipant.objects.create(
        event=event,
        email=email,
        name=email.split("@")[0],
        status=ParticipantStatus.ACTIVE.value,
        registered_at=timezone.now(),
    )


def _campaign(organizer_user, ctf_event, **overrides):
    data = {
        "title": "Kickoff",
        "origin": "organizer_staff",
        "target_event_ids": [ctf_event.id],
        "audience_spec": {"kind": "event", "event_ids": [str(ctf_event.id)]},
        "trigger_spec": {"kind": "manual"},
        "channels": ["in_app"],
        "subject": "Welcome",
        "body": "Read the rules at [rules](/events/rules).",
    }
    data.update(overrides)
    return create_campaign(organizer_user, _workspace_uuid(organizer_user), CampaignDraft(**data))


def test_oversized_audience_is_rejected_before_any_work(organizer_user, ctf_event, settings):
    settings.CTF_COMMUNICATION_MAX_AUDIENCE = 1
    _participant(ctf_event, "a@test.com")
    _participant(ctf_event, "b@test.com")
    campaign = _campaign(organizer_user, ctf_event)

    with pytest.raises(CTFCommunicationError) as exc:
        release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)

    assert exc.value.code == "CTF_COMMUNICATION_AUDIENCE_TOO_LARGE"
    assert DeliveryAttempt.objects.count() == 0  # fail-closed: nothing materialized


def test_actor_rate_limit_fails_closed(organizer_user, ctf_event, settings):
    settings.CTF_COMMUNICATION_RATE_PER_ACTOR = 1
    _participant(ctf_event, "a@test.com")
    first = _campaign(organizer_user, ctf_event)
    second = _campaign(organizer_user, ctf_event, title="Second")

    release_campaign(first, occurrence_key="occ-1", actor_user_id=organizer_user.id)
    with pytest.raises(CTFCommunicationError) as exc:
        release_campaign(second, occurrence_key="occ-2", actor_user_id=organizer_user.id)

    assert exc.value.code == "CTF_COMMUNICATION_RATE_LIMITED"


def test_outstanding_workspace_backlog_is_bounded(organizer_user, ctf_event, settings):
    settings.CTF_COMMUNICATION_MAX_OUTSTANDING_PER_WORKSPACE = 1
    _participant(ctf_event, "a@test.com")
    _participant(ctf_event, "b@test.com")
    campaign = _campaign(organizer_user, ctf_event)

    with pytest.raises(CTFCommunicationError) as exc:
        release_campaign(campaign, occurrence_key="occ", actor_user_id=organizer_user.id)

    assert exc.value.code == "CTF_COMMUNICATION_BACKLOG_FULL"


def test_replay_does_not_double_reserve_capacity(organizer_user, ctf_event, settings):
    # A per-actor budget of 1 admits exactly one genuine release; a replay of the
    # SAME occurrence must return the existing intent without consuming budget again.
    settings.CTF_COMMUNICATION_RATE_PER_ACTOR = 1
    _participant(ctf_event, "a@test.com")
    campaign = _campaign(organizer_user, ctf_event)

    first = release_campaign(campaign, occurrence_key="dup", actor_user_id=organizer_user.id)
    second = release_campaign(campaign, occurrence_key="dup", actor_user_id=organizer_user.id)

    assert first.id == second.id  # replay short-circuits before backpressure; no double reservation
