"""CTF model-access management API — event assessment and participant read (M09, #2126).

Boundary behavior: authentication/scope parity, organizer authority mapping, and
the participant range-scoped redaction. Deep event/capacity logic is covered by
the capacity service tests; here the services are stubbed to drive the DRF
boundary and the participant redaction contract.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from ctf.api._base import _CtfApiError
from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import CTF_PLAY_READ, MODEL_ACCESS_EVENT_READ, MODEL_ACCESS_PARTICIPANT_READ

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("personal_token_use_grant")]

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(username="u", email="u@example.com", password="pw")


def _session(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _token(user, *scopes) -> APIClient:
    _, raw = ApiToken.create_token(name="m9", created_by=user, scopes=list(scopes))
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


class TestEventAssessment:
    def _url(self, event_id) -> str:
        return f"/api/v1/ctf/events/{event_id}/model-access/assessment/"

    @pytest.fixture
    def organizer(self, monkeypatch):
        # Admit the coarse organizer gate; per-object authority is _resolve_owned_event.
        monkeypatch.setattr("ctf.api._base.HasCTFEventAdminAccess.has_permission", lambda self, r, v: True)

    def test_available_summary(self, user, organizer, monkeypatch):
        monkeypatch.setattr("ctf.api.organizer.model_access._resolve_owned_event", lambda *a, **k: object())
        monkeypatch.setattr(
            "ctf.services.range.capacity.assess_declared_capacity",
            lambda *a, **k: {"outcome": "admit", "blocking": False, "partition": "MAIN", "reason_codes": ["ok"]},
        )
        response = _session(user).get(self._url(uuid4()))
        assert response.status_code == 200
        body = response.json()
        assert body["available"] is True
        assert body["outcome"] == "admit"
        assert body["reason_codes"] == ["ok"]

    def test_no_declaration_is_unavailable_not_a_positive_decision(self, user, organizer, monkeypatch):
        monkeypatch.setattr("ctf.api.organizer.model_access._resolve_owned_event", lambda *a, **k: object())
        monkeypatch.setattr("ctf.services.range.capacity.assess_declared_capacity", lambda *a, **k: None)
        response = _session(user).get(self._url(uuid4()))
        assert response.status_code == 200
        body = response.json()
        assert body == {"available": False, "outcome": None, "blocking": None, "partition": None, "reason_codes": []}

    def test_unauthorized_event_maps_error(self, user, organizer, monkeypatch):
        def _deny(*a, **k):
            raise _CtfApiError(code="not_found", message="Event not found", status_code=404)

        monkeypatch.setattr("ctf.api.organizer.model_access._resolve_owned_event", _deny)
        assert _session(user).get(self._url(uuid4())).status_code == 404

    def test_token_without_event_scope_is_rejected(self, user, organizer, monkeypatch):
        monkeypatch.setattr("ctf.api.organizer.model_access._resolve_owned_event", lambda *a, **k: object())
        monkeypatch.setattr("ctf.services.range.capacity.assess_declared_capacity", lambda *a, **k: None)
        assert _token(user, CTF_PLAY_READ).get(self._url(uuid4())).status_code == 403
        assert _token(user, MODEL_ACCESS_EVENT_READ).get(self._url(uuid4())).status_code == 200


class TestParticipantModelAccess:
    URL = "/api/v1/ctf/me/model-access/"

    @pytest.fixture
    def viewing(self, monkeypatch):
        monkeypatch.setattr("ctf.api._base.HasCTFParticipant.has_permission", lambda self, r, v: True)

    def test_redacts_to_state_and_logical_aliases_only(self, user, viewing, monkeypatch):
        participant = type("P", (), {"range_instance_id": 42})()
        monkeypatch.setattr("ctf.api.participant_views._resolve_active_participant", lambda request: participant)
        monkeypatch.setattr(
            "cms.services.get_range_model_policy_status_for_instance",
            lambda instance_id: {
                "state": "active",
                "assignments": [
                    {
                        "workload": "primary",
                        "logical_alias": "coding-main",
                        "provider": "vertex-v1",
                        "model": "secret-model",
                        "region": "us-central1",
                    }
                ],
            },
        )
        response = _session(user).get(self.URL)
        assert response.status_code == 200
        body = response.json()
        assert body == {"state": "active", "aliases": ["coding-main"]}
        # No operator/source coordinates leak to a participant.
        raw = response.content.decode()
        assert "vertex-v1" not in raw
        assert "secret-model" not in raw
        assert "us-central1" not in raw

    def test_no_range_reports_unavailable(self, user, viewing, monkeypatch):
        participant = type("P", (), {"range_instance_id": None})()
        monkeypatch.setattr("ctf.api.participant_views._resolve_active_participant", lambda request: participant)
        response = _session(user).get(self.URL)
        assert response.status_code == 200
        assert response.json() == {"state": "unavailable", "aliases": []}

    def test_token_needs_participant_scope(self, user, viewing, monkeypatch):
        participant = type("P", (), {"range_instance_id": None})()
        monkeypatch.setattr("ctf.api.participant_views._resolve_active_participant", lambda request: participant)
        assert _token(user, CTF_PLAY_READ).get(self.URL).status_code == 403
        assert _token(user, MODEL_ACCESS_PARTICIPANT_READ).get(self.URL).status_code == 200
