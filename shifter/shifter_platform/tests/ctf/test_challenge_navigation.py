"""Tests for CTF challenge management.

Tests for:
- Challenge forms
- Challenge views (list, create, detail, edit)
- Challenge services
- Multi-flag support (CTFFlag model, add_flag, remove_flag, verify_flag)
"""

from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse

from ctf.enums import ChallengeCategory, ChallengeDifficulty, EventStatus
from ctf.forms import CTFChallengeForm
from ctf.models import CTFChallenge, CTFSubmission

# =============================================================================
# Form Tests
# =============================================================================


class TestNextChallengeNavigation:
    """Tests for next challenge navigation (CTF-121)."""

    def test_form_queryset_excludes_self(self, ctf_event_draft):
        """Form next_challenge queryset excludes the challenge being edited."""
        c1 = CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="C1",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="C2",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h2",
        )
        form = CTFChallengeForm(instance=c1, event=ctf_event_draft)
        qs = form.fields["next_challenge"].queryset
        assert c1 not in qs
        assert qs.count() == 1

    def test_form_queryset_filters_by_event(self, ctf_event_draft, organizer_user):
        """Form next_challenge queryset only includes same-event challenges."""
        from ctf.models import CTFEvent

        other_event = CTFEvent.objects.create(
            name="Other Event",
            created_by=organizer_user,
            status=EventStatus.DRAFT.value,
            event_start=ctf_event_draft.event_start,
            event_end=ctf_event_draft.event_end,
            scenario_id="basic",
        )
        CTFChallenge.objects.create(
            event=ctf_event_draft,
            name="Same Event",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        CTFChallenge.objects.create(
            event=other_event,
            name="Other Event Challenge",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h2",
        )
        form = CTFChallengeForm(event=ctf_event_draft)
        qs = form.fields["next_challenge"].queryset
        assert qs.count() == 1
        assert qs.first().name == "Same Event"

    def test_next_challenge_link_shown_when_solved(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Solved challenge with next_challenge shows navigation link."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        c1 = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Challenge 1",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        c2 = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Challenge 2",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h2",
        )
        c1.next_challenge = c2
        c1.save()

        p = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
        )
        CTFSubmission.objects.create(
            participant=p,
            challenge=c1,
            submitted_flag="FLAG{x}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": c1.pk})
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert "Challenge 2" in content
        assert str(c2.pk) in content

    def test_next_challenge_link_hidden_when_not_configured(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Solved challenge without next_challenge does not show link."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        c1 = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Solo Challenge",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        p = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
        )
        CTFSubmission.objects.create(
            participant=p,
            challenge=c1,
            submitted_flag="FLAG{x}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": c1.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert "Next:" not in response.content.decode()

    def test_challenge_detail_shows_connection_info_for_matching_target(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Participant challenge detail shows resolved host and port for configured targets."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="RDP Challenge",
            description="Find the target",
            category=ChallengeCategory.NETWORK.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="$2b$12$h3",
            target_instance_name="windows-target",
            target_port=3389,
        )
        CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
            range_instance_id=42,
            range_status="ready",
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": challenge.pk})
        with patch(
            "cms.services.get_range_target_instances",
            return_value=[
                {"name": "windows-target", "private_ip": "10.0.1.10", "os_type": "windows"},
            ],
        ):
            response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert "10.0.1.10:3389" in content
        assert "(windows-target)" in content

    def test_challenge_detail_hides_connection_info_when_target_missing(
        self,
        client,
        ctf_event_active,
        participant_user,
    ):
        """Participant challenge detail omits connection info when no target instance matches."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Missing Target",
            description="Find the target",
            category=ChallengeCategory.NETWORK.value,
            points=200,
            difficulty=ChallengeDifficulty.MEDIUM.value,
            flag_hash="$2b$12$h4",
            target_instance_name="windows-target",
            target_port=3389,
        )
        CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
            range_instance_id=42,
            range_status="ready",
        )

        client.force_login(participant_user)
        url = reverse("ctf:challenge_detail", kwargs={"challenge_id": challenge.pk})
        with patch("cms.services.get_range_target_instances", return_value=[]):
            response = client.get(url)

        assert response.status_code == 200
        assert "10.0.1.10" not in response.content.decode()


class TestOrganizerDashboard:
    """Tests for the enhanced organizer dashboard (CTF-1301)."""

    def test_dashboard_context_with_active_event(
        self,
        authenticated_organizer_client,
        ctf_event_active,
    ):
        """Dashboard includes active_events_data when active events exist."""
        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "active_events_data" in response.context
        assert len(response.context["active_events_data"]) == 1
        item = response.context["active_events_data"][0]
        assert item["event"].pk == ctf_event_active.pk
        assert "stats" in item
        assert "status_form" in item
        assert "range_ready" in item

    def test_dashboard_range_overview(
        self,
        authenticated_organizer_client,
        ctf_event_active,
    ):
        """Dashboard context includes range provisioning counts."""
        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert "range_ready" in response.context
        assert "range_provisioning" in response.context
        assert "range_error" in response.context

    def test_dashboard_activity_feed_with_submissions(
        self,
        authenticated_organizer_client,
        ctf_event_active,
        participant_user,
    ):
        """Dashboard shows recent submissions in activity feed."""
        from ctf.enums import ParticipantStatus
        from ctf.models import CTFParticipant

        challenge = CTFChallenge.objects.create(
            event=ctf_event_active,
            name="Dashboard Test",
            description="d",
            category=ChallengeCategory.WEB.value,
            points=100,
            difficulty=ChallengeDifficulty.EASY.value,
            flag_hash="$2b$12$h1",
        )
        p = CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Player",
            status=ParticipantStatus.ACTIVE.value,
            registered_at=ctf_event_active.event_start,
        )
        CTFSubmission.objects.create(
            participant=p,
            challenge=challenge,
            submitted_flag="FLAG{x}",
            is_correct=True,
            points_awarded=100,
            attempt_number=1,
        )

        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert len(response.context["recent_activity"]) == 1
        assert response.context["recent_activity"][0].is_correct is True

    def test_dashboard_no_active_events(
        self,
        authenticated_organizer_client,
        ctf_event_draft,
    ):
        """Dashboard works with no active events (empty sections)."""
        url = reverse("ctf:admin_dashboard")
        response = authenticated_organizer_client.get(url)
        assert response.status_code == 200
        assert response.context["active_events_data"] == []
        assert response.context["recent_activity"] == []

    def test_dashboard_quick_controls_post_pauses_event(
        self,
        authenticated_organizer_client,
        ctf_event_active,
    ):
        """Quick controls form POST to event detail pauses the active event."""
        url = reverse("ctf:admin_event_detail", kwargs={"event_id": ctf_event_active.pk})
        response = authenticated_organizer_client.post(url, {"action": "pause"})
        assert response.status_code == 302
        ctf_event_active.refresh_from_db()
        assert ctf_event_active.status == "paused"
