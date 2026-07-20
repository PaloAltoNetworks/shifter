# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT
"""Tests for CTF submission-service read projections.

Covers ``get_participant_solve_history`` — the participant-safe, correct-solve
projection backing the scoreboard row drill-down (issue #521 / CTF-401).
"""

from __future__ import annotations

import pytest

from ctf.services.submission import get_participant_solve_history

pytestmark = pytest.mark.django_db


class TestGetParticipantSolveHistory:
    """The drill-down history must be correct-solves-only and secret-safe."""

    def test_returns_only_correct_solves_with_safe_fields(
        self, ctf_participant, ctf_submission_correct, ctf_submission_incorrect, ctf_challenge
    ):
        """Only correct solves appear, projected to non-secret fields."""
        history = get_participant_solve_history(ctf_participant.id)

        assert len(history) == 1
        entry = history[0]
        assert entry["challenge_name"] == ctf_challenge.name
        assert entry["category"] == ctf_challenge.category
        assert entry["points"] == ctf_submission_correct.points_awarded
        assert "solved_at" in entry

        # The projection must never leak the submitted flag, the attempt IP,
        # or any incorrect-attempt detail to a participant-visible surface.
        assert "submitted_flag" not in entry
        assert "ip_address" not in entry
        assert ctf_submission_correct.submitted_flag not in str(entry)
        assert ctf_submission_incorrect.submitted_flag not in str(entry)
        assert "192.168.1.1" not in str(entry)

    def test_empty_when_no_correct_solves(self, ctf_participant, ctf_submission_incorrect):
        """A participant with only incorrect attempts has an empty history."""
        assert get_participant_solve_history(ctf_participant.id) == []

    def test_freeze_cutoff_excludes_post_freeze_solves(self, ctf_participant, ctf_challenge, ctf_event):
        """When a freeze cutoff is supplied, solves after it are hidden — the
        drill-down must match the frozen scoreboard's visibility (issue #521)."""
        from datetime import timedelta

        from django.utils import timezone

        from ctf.models import CTFChallenge, CTFSubmission

        second_challenge = CTFChallenge.objects.create(
            event=ctf_event,
            name="Second Challenge",
            description="Another challenge",
            category=ctf_challenge.category,
            points=150,
            difficulty=ctf_challenge.difficulty,
            flag_hash="$2b$12$second_hash_placeholder",
            flag_format="FLAG{...}",
        )

        freeze_at = timezone.now()
        before = CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=ctf_challenge,
            submitted_flag="FLAG{before}",
            is_correct=True,
            points_awarded=ctf_challenge.points,
            attempt_number=1,
        )
        CTFSubmission.objects.filter(pk=before.pk).update(submitted_at=freeze_at - timedelta(minutes=5))
        after = CTFSubmission.objects.create(
            participant=ctf_participant,
            challenge=second_challenge,
            submitted_flag="FLAG{after}",
            is_correct=True,
            points_awarded=second_challenge.points,
            attempt_number=1,
        )
        CTFSubmission.objects.filter(pk=after.pk).update(submitted_at=freeze_at + timedelta(minutes=5))

        frozen = get_participant_solve_history(ctf_participant.id, freeze_at=freeze_at)
        assert len(frozen) == 1

        unfrozen = get_participant_solve_history(ctf_participant.id)
        assert len(unfrozen) == 2
