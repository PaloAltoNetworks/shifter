# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT
"""Tests for the CTF participant scoreboard and solve-history drill-down views.

Covers the scoreboard `participant_id` wiring (the "You" highlight) and the
own-row solve-history drill-down with its own-or-organizer gate and
frozen-scoreboard cutoff (issue #521 / CTF-401, CTF-1404).
"""

from __future__ import annotations

from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

# The scoreboard/solve-history templates use {% static %}; force the
# non-manifest static storage so rendering does not require a built manifest.
_SIMPLE_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class TestScoreboardParticipantIdWiring:
    """#521 / CTF-401: the scoreboard view must expose the viewer's
    ``participant_id`` so the "You" row highlight works on initial render and
    on the auto-refresh JS path (both key on ``participant_id``)."""

    @override_settings(STORAGES=_SIMPLE_STORAGES)
    def test_scoreboard_context_includes_participant_id(
        self, authenticated_participant_client, participant_user, ctf_participant, ctf_event
    ):
        from management.services import set_active_ctf_event

        set_active_ctf_event(participant_user, ctf_event.pk)

        response = authenticated_participant_client.get(reverse("ctf:scoreboard"))

        assert response.status_code == 200
        assert response.context["participant_id"] == str(ctf_participant.id)
        # The own row links to the solve-history drill-down.
        solve_history_url = reverse("ctf:participant_solve_history", kwargs={"participant_id": ctf_participant.id})
        assert solve_history_url in response.content.decode()


class TestParticipantSolveHistoryView:
    """#521 / CTF-401: own-row solve-history drill-down. Gate is
    own-participant-or-organizer; the projection is correct-solves-only and
    must not leak submitted flags or attempt IPs."""

    def _url(self, participant):
        return reverse("ctf:participant_solve_history", kwargs={"participant_id": participant.id})

    @override_settings(STORAGES=_SIMPLE_STORAGES)
    def test_owner_sees_correct_solves_without_secrets(
        self,
        authenticated_participant_client,
        ctf_participant,
        ctf_challenge,
        ctf_submission_correct,
        ctf_submission_incorrect,
    ):
        """The participant can open their own history; it shows the solved
        challenge but never the submitted flag or attempt IP."""
        response = authenticated_participant_client.get(self._url(ctf_participant))

        assert response.status_code == 200
        body = response.content.decode()
        assert ctf_challenge.name in body
        assert ctf_submission_correct.submitted_flag not in body
        assert "192.168.1.1" not in body

    def test_other_participant_history_is_forbidden(
        self,
        client,
        second_participant_user,
        ctf_participant,
    ):
        """A participant may not open another participant's solve history."""
        client.force_login(second_participant_user)

        response = client.get(self._url(ctf_participant))

        assert response.status_code == 403

    @override_settings(STORAGES=_SIMPLE_STORAGES)
    def test_event_organizer_can_view_participant_history(
        self,
        authenticated_organizer_client,
        ctf_participant,
        ctf_submission_correct,
    ):
        """The organizer that owns the event may view a participant's history."""
        response = authenticated_organizer_client.get(self._url(ctf_participant))

        assert response.status_code == 200

    def test_unknown_participant_returns_404(self, authenticated_participant_client):
        import uuid

        url = reverse("ctf:participant_solve_history", kwargs={"participant_id": uuid.uuid4()})

        response = authenticated_participant_client.get(url)

        assert response.status_code == 404

    @override_settings(STORAGES=_SIMPLE_STORAGES)
    def test_frozen_scoreboard_hides_post_freeze_solves_from_owner(
        self, authenticated_participant_client, ctf_participant, ctf_challenge, ctf_event
    ):
        """A non-organizer's drill-down must apply the frozen-scoreboard cutoff,
        so post-freeze solves are hidden just as on the scoreboard (issue #521)."""
        from ctf.enums import EventStatus
        from ctf.models import CTFChallenge, CTFSubmission

        now = timezone.now()
        freeze_at = now - timedelta(minutes=1)
        ctf_event.status = EventStatus.ACTIVE.value
        ctf_event.event_start = now - timedelta(hours=2)
        ctf_event.event_end = now + timedelta(hours=6)
        ctf_event.scoreboard_freeze_at = freeze_at
        ctf_event.save(update_fields=["status", "event_start", "event_end", "scoreboard_freeze_at"])

        post_freeze_challenge = CTFChallenge.objects.create(
            event=ctf_event,
            name="Post Freeze Challenge",
            description="Solved after the freeze",
            category=ctf_challenge.category,
            points=150,
            difficulty=ctf_challenge.difficulty,
            flag_hash="$2b$12$postfreeze_hash_placeholder",
            flag_format="FLAG{...}",
        )
        pre = CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=ctf_challenge,
            submitted_flag="FLAG{pre}",
            is_correct=True,
            points_awarded=ctf_challenge.points,
            attempt_number=1,
        )
        CTFSubmission.objects.filter(pk=pre.pk).update(submitted_at=freeze_at - timedelta(minutes=5))
        post = CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=post_freeze_challenge,
            submitted_flag="FLAG{post}",
            is_correct=True,
            points_awarded=post_freeze_challenge.points,
            attempt_number=1,
        )
        CTFSubmission.objects.filter(pk=post.pk).update(submitted_at=freeze_at + timedelta(minutes=5))

        response = authenticated_participant_client.get(self._url(ctf_participant))

        assert response.status_code == 200
        body = response.content.decode()
        assert ctf_challenge.name in body
        assert "Post Freeze Challenge" not in body

    @override_settings(STORAGES=_SIMPLE_STORAGES)
    def test_frozen_scoreboard_organizer_sees_post_freeze_solves(
        self, authenticated_organizer_client, ctf_participant, ctf_challenge, ctf_event
    ):
        """The organizer bypasses the freeze cutoff and sees post-freeze solves,
        exercising the `not is_event_organizer` bypass branch (issue #521)."""
        from ctf.enums import EventStatus
        from ctf.models import CTFChallenge, CTFSubmission

        now = timezone.now()
        freeze_at = now - timedelta(minutes=1)
        ctf_event.status = EventStatus.ACTIVE.value
        ctf_event.event_start = now - timedelta(hours=2)
        ctf_event.event_end = now + timedelta(hours=6)
        ctf_event.scoreboard_freeze_at = freeze_at
        ctf_event.save(update_fields=["status", "event_start", "event_end", "scoreboard_freeze_at"])

        post_freeze_challenge = CTFChallenge.objects.create(
            event=ctf_event,
            name="Post Freeze Challenge",
            description="Solved after the freeze",
            category=ctf_challenge.category,
            points=150,
            difficulty=ctf_challenge.difficulty,
            flag_hash="$2b$12$postfreeze_hash_placeholder",
            flag_format="FLAG{...}",
        )
        post = CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=post_freeze_challenge,
            submitted_flag="FLAG{post}",
            is_correct=True,
            points_awarded=post_freeze_challenge.points,
            attempt_number=1,
        )
        CTFSubmission.objects.filter(pk=post.pk).update(submitted_at=freeze_at + timedelta(minutes=5))

        response = authenticated_organizer_client.get(self._url(ctf_participant))

        assert response.status_code == 200
        assert "Post Freeze Challenge" in response.content.decode()
