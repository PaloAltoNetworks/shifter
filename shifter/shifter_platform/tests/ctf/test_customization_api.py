"""Analytics, custom pages, theming, and extension registries (CTF-1302/1303/1401/1402)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.models import CTFEventPage, CTFParticipant
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


class TestAnalytics:
    def test_dashboard_aggregates(self, ctf_event_active, ctf_challenge, authenticated_organizer_client):
        from ctf.models import CTFSubmission

        ctf_challenge.event = ctf_event_active
        ctf_challenge.save(update_fields=["event"])
        participant = CTFParticipant.objects.create(
            event=ctf_event_active,
            email="solver@test.com",
            name="Solver",
            status="active",
            registered_at=timezone.now(),
            cached_score=100,
            cached_solve_count=1,
            last_active_at=timezone.now(),
        )
        CTFSubmission.objects.create(
            participant=participant,
            challenge=ctf_challenge,
            submitted_flag="x",
            is_correct=True,
            points_awarded=100,
        )

        resp = call_json(
            authenticated_organizer_client, "get", "api_event_analytics", kwargs={"event_id": ctf_event_active.id}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert sum(bucket["count"] for bucket in body["score_distribution"]) == 1
        assert body["solve_timeline"]
        assert body["solve_timeline"][0]["solves"] == 1
        challenge_row = next(c for c in body["challenges"] if c["name"] == ctf_challenge.name)
        assert challenge_row["solves"] == 1
        assert challenge_row["solve_rate"] == 1.0
        assert body["engagement"]["registered"] == 1
        assert body["engagement"]["avg_challenges_attempted"] == 1.0


class TestCustomPages:
    def test_crud_and_participant_read(self, ctf_event_active, participant_user, authenticated_organizer_client):
        from django.test import Client

        from management.services import set_active_ctf_event

        created = call_json(
            authenticated_organizer_client,
            "post",
            "api_event_pages",
            kwargs={"event_id": ctf_event_active.id},
            body={"title": "Getting Started", "body": "Read **this** first.", "order": 1},
        )
        assert created.status_code == 201
        assert created.json()["slug"] == "getting-started"

        dup = call_json(
            authenticated_organizer_client,
            "post",
            "api_event_pages",
            kwargs={"event_id": ctf_event_active.id},
            body={"title": "Getting Started", "body": "again"},
        )
        assert dup.status_code == 400

        updated = call_json(
            authenticated_organizer_client,
            "put",
            "api_event_page_detail",
            kwargs={"page_id": created.json()["id"]},
            body={"title": "Start Here"},
        )
        assert updated.json()["title"] == "Start Here"

        CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Reader",
            status="active",
            registered_at=timezone.now(),
        )
        set_active_ctf_event(participant_user, ctf_event_active.pk)
        reader = Client()
        reader.force_login(participant_user)
        pages = call_json(reader, "get", "api_me_pages").json()
        assert [p["title"] for p in pages["pages"]] == ["Start Here"]

        gone = call_json(
            authenticated_organizer_client,
            "delete",
            "api_event_page_detail",
            kwargs={"page_id": created.json()["id"]},
        )
        assert gone.status_code == 200
        assert not CTFEventPage.objects.filter(deleted_at__isnull=True).exists()


class TestTheming:
    def test_branding_flows_to_participant_surface(
        self, ctf_event_active, participant_user, authenticated_organizer_client
    ):
        from django.test import Client

        from management.services import set_active_ctf_event

        resp = call_json(
            authenticated_organizer_client,
            "put",
            "api_event_detail",
            kwargs={"event_id": ctf_event_active.id},
            body={"logo_url": "https://cdn.example.test/logo.png", "theme_color": "#22d3ee"},
        )
        assert resp.status_code == 200, resp.content

        CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="Fan",
            status="active",
            registered_at=timezone.now(),
        )
        set_active_ctf_event(participant_user, ctf_event_active.pk)
        viewer = Client()
        viewer.force_login(participant_user)
        me = call_json(viewer, "get", "api_participant_current_event").json()
        assert me["event"]["logo_url"] == "https://cdn.example.test/logo.png"
        assert me["event"]["theme_color"] == "#22d3ee"


class TestExtensionRegistries:
    def test_custom_flag_validator_dispatch(self, ctf_challenge):
        from ctf.extensions import _flag_validators, register_flag_validator
        from ctf.models import CTFFlag
        from ctf.services.challenge import verify_flag

        register_flag_validator("parity", lambda flag_obj, submitted: submitted.endswith("42"))
        try:
            CTFFlag.objects.create(challenge=ctf_challenge, flag_type="parity", flag_hash="unused", order=1)
            assert verify_flag(ctf_challenge, "anything-42") is True
            assert verify_flag(ctf_challenge, "anything-41") is False
        finally:
            _flag_validators.pop("parity", None)

    def test_custom_scoring_strategy_dispatch(self, ctf_event, ctf_challenge):
        from ctf.extensions import _scoring_strategies, register_scoring_strategy
        from ctf.services.scoring import calculate_solve_points

        class FlatScoring:
            @staticmethod
            def points_for_solve(challenge, total_hint_penalty):
                return 7

        register_scoring_strategy("flat", FlatScoring())
        try:
            ctf_event.scoring_mode = "flat"
            ctf_event.save(update_fields=["scoring_mode", "updated_at"])
            assert calculate_solve_points(ctf_event, ctf_challenge, 0) == 7
        finally:
            _scoring_strategies.pop("flat", None)

    def test_registered_mode_passes_event_validation(self, ctf_event_draft, organizer_user):
        from ctf.exceptions import CTFValidationError
        from ctf.extensions import _scoring_strategies, register_scoring_strategy
        from ctf.services import update_event

        with pytest.raises(CTFValidationError):
            update_event(ctf_event_draft.pk, {"scoring_mode": "golf"})

        register_scoring_strategy("golf", type("S", (), {"points_for_solve": staticmethod(lambda c, p: 1)})())
        try:
            updated = update_event(ctf_event_draft.pk, {"scoring_mode": "golf"})
            assert updated.scoring_mode == "golf"
        finally:
            _scoring_strategies.pop("golf", None)
