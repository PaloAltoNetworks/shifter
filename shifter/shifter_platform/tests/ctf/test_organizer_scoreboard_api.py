# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the organizer monitoring scoreboard API (#1372).

``GET /api/v1/ctf/events/<event_id>/organizer-scoreboard/`` is the organizer's
full-visibility read used by the monitoring workspace. Unlike the public
scoreboard it must ignore the event's ``scoreboard_visibility`` mode and its freeze
window (``freeze_at=None``), so an organizer always sees real-time rankings. It
still enforces event ownership (403 for a non-owner, 404 for an unknown event).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.utils import timezone

from ctf.enums import EventStatus
from ctf.models import CTFSubmission

from ._api_flow_helpers import call_json


def _row_for(body: dict, participant) -> dict | None:
    """Return the ranking row for ``participant`` from a scoreboard response."""
    return next(
        (row for row in body["rankings"] if row["participant_id"] == str(participant.id)),
        None,
    )


class TestOrganizerScoreboardApi:
    """``GET /api/v1/ctf/events/<event_id>/organizer-scoreboard/``."""

    def test_owner_sees_rankings_when_scoreboard_hidden(
        self,
        authenticated_organizer_client,
        ctf_event,
        ctf_participant,
        ctf_challenge,
    ):
        """The owning organizer gets full rankings even when the board is hidden
        from participants (``scoreboard_visibility=hidden``)."""
        from ctf.services.scoring import recompute_participant_score

        ctf_event.scoreboard_visibility = "hidden"
        ctf_event.save(update_fields=["scoreboard_visibility"])

        CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=ctf_challenge,
            submitted_flag="FLAG{correct}",
            is_correct=True,
            points_awarded=ctf_challenge.points,
            attempt_number=1,
        )
        recompute_participant_score(ctf_participant.id)

        response = call_json(
            authenticated_organizer_client,
            "get",
            "api_organizer_scoreboard",
            kwargs={"event_id": ctf_event.id},
        )

        assert response.status_code == 200
        body = response.json()
        row = _row_for(body, ctf_participant)
        assert row is not None
        assert row["score"] == ctf_challenge.points
        assert row["solve_count"] == 1

    def test_frozen_event_reflects_post_freeze_solves(
        self,
        authenticated_organizer_client,
        ctf_event,
        ctf_participant,
        ctf_challenge,
    ):
        """On a frozen event the organizer board computes as of now
        (``freeze_at=None``): a solve recorded after the freeze time is reflected
        in the ranking, unlike the public frozen board which would hide it."""
        from ctf.services.scoring import recompute_participant_score

        now = timezone.now()
        freeze_at = now - timedelta(minutes=1)
        ctf_event.status = EventStatus.ACTIVE.value
        ctf_event.event_start = now - timedelta(hours=2)
        ctf_event.event_end = now + timedelta(hours=6)
        ctf_event.scoreboard_freeze_at = freeze_at
        ctf_event.save(update_fields=["status", "event_start", "event_end", "scoreboard_freeze_at"])

        submission = CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=ctf_challenge,
            submitted_flag="FLAG{post}",
            is_correct=True,
            points_awarded=ctf_challenge.points,
            attempt_number=1,
        )
        # Move the solve past the freeze cutoff; the public board would exclude it.
        CTFSubmission.objects.filter(pk=submission.pk).update(submitted_at=freeze_at + timedelta(minutes=5))
        recompute_participant_score(ctf_participant.id)

        response = call_json(
            authenticated_organizer_client,
            "get",
            "api_organizer_scoreboard",
            kwargs={"event_id": ctf_event.id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["frozen"] is True
        row = _row_for(body, ctf_participant)
        assert row is not None
        # The post-freeze solve is counted (freeze_at=None); a freeze-aware read
        # would report a score of 0 here.
        assert row["score"] == ctf_challenge.points
        assert row["solve_count"] == 1

    def test_non_owner_organizer_is_forbidden(
        self,
        client,
        second_organizer_user,
        ctf_event,
    ):
        """An organizer who does not own the event is denied (403)."""
        client.force_login(second_organizer_user)

        response = call_json(
            client,
            "get",
            "api_organizer_scoreboard",
            kwargs={"event_id": ctf_event.id},
        )

        assert response.status_code == 403

    def test_unknown_event_returns_404(self, authenticated_organizer_client):
        """An unknown event id resolves to a 404 envelope."""
        response = call_json(
            authenticated_organizer_client,
            "get",
            "api_organizer_scoreboard",
            kwargs={"event_id": uuid.uuid4()},
        )

        assert response.status_code == 404
