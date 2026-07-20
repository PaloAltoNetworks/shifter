"""DRF boundary coverage for the canonical CTF API (PLAT-106 / #1121)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken

pytestmark = pytest.mark.django_db

EVENT_LIST_URL = "/api/v1/ctf/events/"
SUBMISSIONS_URL = "/api/v1/ctf/submissions/"


def _bearer(client: APIClient, raw: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def _token(user, *granted_scopes: str) -> str:
    _token_obj, raw = ApiToken.create_token(name="ctf-api", created_by=user, scopes=list(granted_scopes))
    return raw


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


class TestCTFEventTokenAccess:
    def test_event_read_token_lists_owned_events(self, api_client: APIClient, organizer_user, ctf_event):
        raw = _token(organizer_user, scopes.CTF_EVENT_READ)

        response = _bearer(api_client, raw).get(EVENT_LIST_URL)

        assert response.status_code == 200
        assert response.json()["events"][0]["id"] == str(ctf_event.id)

    def test_token_without_event_read_scope_is_forbidden(self, api_client: APIClient, organizer_user):
        raw = _token(organizer_user, scopes.CTF_PLAY_WRITE)

        response = _bearer(api_client, raw).get(EVENT_LIST_URL)

        assert response.status_code == 403

    def test_event_scope_does_not_bypass_event_ownership(self, api_client: APIClient, second_organizer_user, ctf_event):
        raw = _token(second_organizer_user, scopes.CTF_EVENT_READ)

        response = _bearer(api_client, raw).get(f"/api/v1/ctf/events/{ctf_event.id}/")

        assert response.status_code == 403

    def test_invalid_bearer_fails_closed_over_logged_in_session(self, api_client: APIClient, organizer_user, ctf_event):
        api_client.force_login(organizer_user)
        api_client.credentials(HTTP_AUTHORIZATION="Bearer shf_missing.invalid")

        response = api_client.get(EVENT_LIST_URL)

        assert response.status_code == 401

    def test_canonical_json_parse_error_uses_shared_envelope(self, api_client: APIClient, organizer_user):
        raw = _token(organizer_user, scopes.CTF_EVENT_WRITE)

        response = _bearer(api_client, raw).post(
            EVENT_LIST_URL,
            data="not-json",
            content_type="application/json",
        )

        assert response.status_code == 400
        assert isinstance(response.json()["error"], dict)


class TestCTFPlayTokenAccess:
    def test_play_write_token_reaches_flag_submission_without_csrf(
        self, api_client: APIClient, participant_user, ctf_participant, ctf_challenge
    ):
        raw = _token(participant_user, scopes.CTF_PLAY_WRITE)

        response = _bearer(api_client, raw).post(
            f"/api/v1/ctf/challenges/{ctf_challenge.id}/submit/",
            {"flag": "FLAG{guess}"},
            format="json",
        )

        assert response.status_code in (200, 400, 429)

    def test_play_write_endpoint_rejects_event_scope(
        self, api_client: APIClient, participant_user, ctf_participant, ctf_challenge
    ):
        raw = _token(participant_user, scopes.CTF_EVENT_READ)

        response = _bearer(api_client, raw).post(
            f"/api/v1/ctf/challenges/{ctf_challenge.id}/submit/",
            {"flag": "FLAG{guess}"},
            format="json",
        )

        assert response.status_code == 403

    def test_play_read_scope_can_read_submission_history(
        self, api_client: APIClient, participant_user, ctf_participant
    ):
        from management.services import set_active_ctf_event

        set_active_ctf_event(participant_user, ctf_participant.event_id)
        raw = _token(participant_user, scopes.CTF_PLAY_READ)

        response = _bearer(api_client, raw).get(SUBMISSIONS_URL)

        assert response.status_code == 200
        assert response.json() == {"submissions": [], "total": 0}

    def test_play_read_scope_can_request_range_access(self, api_client: APIClient, participant_user, ctf_participant):
        raw = _token(participant_user, scopes.CTF_PLAY_READ)

        response = _bearer(api_client, raw).post("/api/v1/ctf/range/access/")

        assert response.status_code == 200
        assert response.json()["redirect"]


class TestCTFPublicScoreboard:
    def test_public_scoreboard_allows_anonymous_read(self, api_client: APIClient, ctf_event):
        ctf_event.scoreboard_visibility = "public"
        ctf_event.save(update_fields=["scoreboard_visibility"])

        response = api_client.get(f"/api/v1/ctf/events/{ctf_event.id}/scoreboard/")

        assert response.status_code == 200
        assert response.json()["event_id"] == str(ctf_event.id)

    def test_participants_mode_blocks_anonymous(self, api_client: APIClient, ctf_event):
        """CTF-404: participants-only boards are hidden from unauthenticated viewers."""
        ctf_event.scoreboard_visibility = "participants"
        ctf_event.save(update_fields=["scoreboard_visibility"])

        response = api_client.get(f"/api/v1/ctf/events/{ctf_event.id}/scoreboard/")

        assert response.status_code == 200
        assert response.json() == {"scoreboard_hidden": True}

    def test_participants_mode_serves_registered_participant(
        self, api_client: APIClient, ctf_event, ctf_participant, participant_user
    ):
        ctf_event.scoreboard_visibility = "participants"
        ctf_event.save(update_fields=["scoreboard_visibility"])
        api_client.force_authenticate(user=participant_user)

        response = api_client.get(f"/api/v1/ctf/events/{ctf_event.id}/scoreboard/")

        assert response.status_code == 200
        assert response.json()["event_id"] == str(ctf_event.id)

    def test_hidden_mode_blocks_even_participants(
        self, api_client: APIClient, ctf_event, ctf_participant, participant_user
    ):
        ctf_event.scoreboard_visibility = "hidden"
        ctf_event.save(update_fields=["scoreboard_visibility"])
        api_client.force_authenticate(user=participant_user)

        response = api_client.get(f"/api/v1/ctf/events/{ctf_event.id}/scoreboard/")

        assert response.status_code == 200
        assert response.json() == {"scoreboard_hidden": True}

    def test_public_exception_does_not_apply_to_score_timeline(self, api_client: APIClient, ctf_participant):
        response = api_client.get(f"/api/v1/ctf/participants/{ctf_participant.id}/score-timeline/")

        assert response.status_code == 401
