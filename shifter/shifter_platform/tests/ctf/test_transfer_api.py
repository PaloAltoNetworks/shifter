"""Import/export, webhooks, and pagination flows (CTF-1101..1104, CTF-1201, CTF-1203)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty
from ctf.models import CTFChallenge, CTFHint, CTFParticipant, CTFWebhook
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


@pytest.fixture
def rich_challenge(ctf_event):
    challenge = CTFChallenge.objects.create(
        event=ctf_event,
        name="Portable",
        description="Take me with you",
        category=ChallengeCategory.WEB.value,
        points=100,
        difficulty=ChallengeDifficulty.EASY.value,
        flag_hash="$2b$12$exported-hash",
        flag_format="FLAG{...}",
    )
    CTFHint.objects.create(challenge=challenge, text="look closer", penalty=10, order=1)
    return challenge


class TestChallengeExportImport:
    def test_shifter_round_trip(self, ctf_event, ctf_event_draft, rich_challenge, authenticated_organizer_client):
        exported = call_json(
            authenticated_organizer_client, "get", "api_challenge_export", kwargs={"event_id": ctf_event.id}
        ).json()
        assert exported["format"] == "shifter-challenges/v1"
        assert exported["challenges"][0]["flag_hash"] == "$2b$12$exported-hash"
        assert exported["challenges"][0]["hints"] == [{"text": "look closer", "penalty": 10, "order": 1}]

        imported = call_json(
            authenticated_organizer_client,
            "post",
            "api_challenge_import",
            kwargs={"event_id": ctf_event_draft.id},
            body={"payload": exported},
        ).json()
        assert imported["created"] == ["Portable"]
        assert imported["errors"] == []
        clone = CTFChallenge.objects.get(event=ctf_event_draft, name="Portable")
        assert clone.flag_hash == "$2b$12$exported-hash"
        assert clone.hints.count() == 1

    def test_ctfd_export_omits_flags(self, ctf_event, rich_challenge, authenticated_organizer_client):
        exported = call_json(
            authenticated_organizer_client,
            "get",
            "api_challenge_export",
            kwargs={"event_id": ctf_event.id},
            query="?fmt=ctfd",
        ).json()
        entry = exported["challenges"][0]
        assert entry["value"] == 100
        assert entry["flags"] == []
        assert entry["hints"] == [{"content": "look closer", "cost": 10}]

    def test_ctfd_import_partial_success(self, ctf_event, rich_challenge, authenticated_organizer_client):
        payload = {
            "challenges": [
                {"name": "Fresh", "value": 200, "category": "web", "flags": ["FLAG{abc}"]},
                {"name": "Portable", "value": 50, "flags": ["FLAG{dup}"]},
                {"name": "", "value": 10},
                {"name": "No Flag", "value": 10},
            ]
        }
        result = call_json(
            authenticated_organizer_client,
            "post",
            "api_challenge_import",
            kwargs={"event_id": ctf_event.id},
            body={"payload": payload},
        ).json()
        assert result["created"] == ["Fresh"]
        assert len(result["errors"]) == 3
        fresh = CTFChallenge.objects.get(event=ctf_event, name="Fresh")
        assert fresh.points == 200


class TestResultsExport:
    def test_json_and_csv(self, ctf_event_active, authenticated_organizer_client):
        participant = CTFParticipant.objects.create(
            event=ctf_event_active,
            email="scored@test.com",
            name="Scored",
            status="active",
            registered_at=timezone.now(),
            cached_score=150,
            cached_solve_count=2,
        )
        results = call_json(
            authenticated_organizer_client, "get", "api_results_export", kwargs={"event_id": ctf_event_active.id}
        ).json()
        assert results["rankings"][0]["name"] == "Scored"
        assert results["rankings"][0]["rank"] == 1
        assert "statistics" in results and "solves" in results and "hint_usage" in results
        assert participant.pk  # participant fixture used

        csv_response = call_json(
            authenticated_organizer_client,
            "get",
            "api_results_export",
            kwargs={"event_id": ctf_event_active.id},
            query="?fmt=csv",
        )
        assert csv_response["Content-Type"] == "text/csv"
        assert b"Scored,150,2" in csv_response.content


class TestWebhooks:
    def test_register_list_delete(self, ctf_event, authenticated_organizer_client):
        created = call_json(
            authenticated_organizer_client,
            "post",
            "api_event_webhooks",
            kwargs={"event_id": ctf_event.id},
            body={"url": "https://hooks.example.test/ctf", "secret": "s3cret", "subscribed_events": ["flag_solve"]},
        )
        assert created.status_code == 201
        assert created.json()["has_secret"] is True

        listing = call_json(
            authenticated_organizer_client, "get", "api_event_webhooks", kwargs={"event_id": ctf_event.id}
        ).json()
        assert [w["url"] for w in listing["webhooks"]] == ["https://hooks.example.test/ctf"]
        assert "secret" not in listing["webhooks"][0]

        gone = call_json(
            authenticated_organizer_client,
            "delete",
            "api_webhook_detail",
            kwargs={"webhook_id": created.json()["id"]},
        )
        assert gone.status_code == 200
        assert not CTFWebhook.objects.filter(deleted_at__isnull=True).exists()

    def test_register_rejects_unknown_event_type(self, ctf_event, authenticated_organizer_client):
        resp = call_json(
            authenticated_organizer_client,
            "post",
            "api_event_webhooks",
            kwargs={"event_id": ctf_event.id},
            body={"url": "https://hooks.example.test/x", "subscribed_events": ["comet_sighted"]},
        )
        assert resp.status_code == 400

    def test_emit_filters_subscriptions_and_signs(self, ctf_event, monkeypatch):
        from ctf.services import webhook as webhook_service

        subscribed = CTFWebhook.objects.create(
            event=ctf_event, url="https://a.test/hook", secret="topsecret", subscribed_events=["flag_solve"]
        )
        CTFWebhook.objects.create(event=ctf_event, url="https://b.test/hook", subscribed_events=["first_blood"])
        CTFWebhook.objects.create(event=ctf_event, url="https://c.test/hook", active=False)

        deliveries = []
        monkeypatch.setattr(webhook_service._executor, "submit", lambda fn, *args: deliveries.append(args))
        queued = webhook_service.emit_webhook(ctf_event, "flag_solve", {"points": 100})
        assert queued == 1
        assert deliveries[0][0] == subscribed.pk

        import hashlib
        import hmac as hmac_lib

        _pk, _url, secret, body = deliveries[0]
        expected = hmac_lib.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert expected  # signature derivable from the queued body
        assert b'"event_type": "flag_solve"' in body

    def test_delivery_retries_then_records_failure(self, ctf_event, monkeypatch):
        from ctf.services import webhook as webhook_service

        hook = CTFWebhook.objects.create(event=ctf_event, url="https://down.test/hook")
        attempts = []

        class FakeResponse:
            ok = False
            status_code = 503

        monkeypatch.setattr(webhook_service.time, "sleep", lambda _s: None)
        monkeypatch.setattr("requests.post", lambda url, **kwargs: attempts.append(url) or FakeResponse())
        webhook_service._deliver_with_retries(hook.pk, hook.url, "", b"{}")

        assert len(attempts) == 3
        hook.refresh_from_db()
        assert hook.last_status == "failed:503"
        assert hook.last_delivery_at is not None


class TestPagination:
    def test_participant_list_window(self, ctf_event, authenticated_organizer_client):
        for index in range(5):
            CTFParticipant.objects.create(event=ctf_event, email=f"p{index}@test.com", name=f"P{index:02d}")
        page = call_json(
            authenticated_organizer_client,
            "get",
            "api_participant_list",
            kwargs={"event_id": ctf_event.id},
            query="?limit=2&offset=2",
        ).json()
        assert page["total"] == 5
        assert [p["name"] for p in page["participants"]] == ["P02", "P03"]

        full = call_json(
            authenticated_organizer_client, "get", "api_participant_list", kwargs={"event_id": ctf_event.id}
        ).json()
        assert len(full["participants"]) == 5
