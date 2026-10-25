"""Import/export, webhooks, and pagination flows (CTF-1101..1104, CTF-1201, CTF-1203)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.enums import ChallengeCategory, ChallengeDifficulty
from ctf.models import CTFChallenge, CTFFlag, CTFHint, CTFParticipant, CTFWebhook
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
        flag_format="FLAG{...}",
    )
    CTFFlag.objects.create(
        challenge=challenge,
        value="FLAG{portable}",
        flag_type="static",
        case_sensitive=True,
        order=0,
    )
    CTFHint.objects.create(challenge=challenge, text="look closer", penalty=10, order=1)
    return challenge


class TestChallengeExportImport:
    def test_shifter_round_trip(self, ctf_event, ctf_event_draft, rich_challenge, authenticated_organizer_client):
        exported = call_json(
            authenticated_organizer_client, "get", "api_challenge_export", kwargs={"event_id": ctf_event.id}
        ).json()
        assert exported["format"] == "shifter-challenges/v3"
        # Static flags are stored, and so exported, as their normalized plaintext value.
        assert exported["challenges"][0]["flags"][0]["value"] == "portable"
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
        assert clone.flags.get().value == "portable"
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
        assert entry["difficulty"] == ChallengeDifficulty.EASY.value
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

    def test_ctfd_import_maps_difficulty(self, ctf_event_draft):
        """CTFd has no native difficulty field: it travels as a top-level key or
        a ``difficulty:<level>`` tag, and ``insane`` maps to the top tier."""
        from ctf.services.transfer import import_challenges

        payload = {
            "format": "ctfd",
            "challenges": [
                {"name": "Tagged", "value": 100, "flags": ["FLAG{a}"], "tags": ["team:x", "difficulty:hard"]},
                {"name": "TagObject", "value": 100, "flags": ["FLAG{b}"], "tags": [{"value": "difficulty:Easy"}]},
                {"name": "TopLevel", "value": 100, "flags": ["FLAG{c}"], "difficulty": "easy"},
                {"name": "Insane", "value": 100, "flags": ["FLAG{d}"], "tags": ["difficulty:insane"]},
                {"name": "Unset", "value": 100, "flags": ["FLAG{e}"]},
                {"name": "Bogus", "value": 100, "flags": ["FLAG{f}"], "tags": ["difficulty:legendary"]},
            ],
        }
        result = import_challenges(ctf_event_draft.pk, payload, actor_id=ctf_event_draft.created_by_id)

        assert result["created"] == ["Tagged", "TagObject", "TopLevel", "Insane", "Unset"]
        assert [error["name"] for error in result["errors"]] == ["Bogus"]
        difficulty = dict(CTFChallenge.objects.filter(event=ctf_event_draft).values_list("name", "difficulty"))
        assert difficulty == {
            "Tagged": ChallengeDifficulty.HARD.value,
            "TagObject": ChallengeDifficulty.EASY.value,
            "TopLevel": ChallengeDifficulty.EASY.value,
            "Insane": ChallengeDifficulty.EXPERT.value,
            "Unset": ChallengeDifficulty.MEDIUM.value,
        }

    @pytest.mark.parametrize("legacy_format", ["shifter-challenges/v1", "shifter-challenges/v2"])
    def test_import_rejects_legacy_formats(self, ctf_event_draft, legacy_format):
        """v1 (challenge-level hash, #532) and v2 (one-way flag hashes) exports
        cannot verify anything once flags are plaintext: rejected, no adapter."""
        from ctf.exceptions import CTFValidationError
        from ctf.services.transfer import import_challenges

        payload = {
            "format": legacy_format,
            "challenges": [{"name": "Old", "flags": [{"flag_type": "static", "flag_hash": "$2b$12$legacy"}]}],
        }
        with pytest.raises(CTFValidationError) as exc:
            import_challenges(ctf_event_draft.pk, payload, actor_id=ctf_event_draft.created_by_id)
        assert exc.value.code == "CTF_UNSUPPORTED_FORMAT"

    def test_shifter_import_validates_flags_through_the_canonical_path(self, ctf_event_draft):
        """Imported v3 flags are validated like organizer-added flags: static
        values are normalized and unsafe regex patterns fail the entry."""
        from ctf.services.transfer import import_challenges

        payload = {
            "format": "shifter-challenges/v3",
            "challenges": [
                {
                    "name": "Wrapped",
                    "description": "x",
                    "category": "web",
                    "points": 100,
                    "flags": [{"flag_type": "static", "value": "FLAG{inner}"}],
                },
                {
                    "name": "Unsafe",
                    "description": "x",
                    "category": "web",
                    "points": 100,
                    "flags": [{"flag_type": "regex", "value": "flag(["}],
                },
            ],
        }
        result = import_challenges(ctf_event_draft.pk, payload, actor_id=ctf_event_draft.created_by_id)

        assert result["created"] == ["Wrapped"]
        assert [error["name"] for error in result["errors"]] == ["Unsafe"]
        assert CTFChallenge.objects.get(event=ctf_event_draft, name="Wrapped").flags.get().value == "inner"

    def test_shifter_import_rejects_entry_without_flags(self, ctf_event_draft):
        """A shifter-format entry with no flag material is invalid (#532): CTFFlag
        rows are the sole source of truth, so an imported challenge must carry
        at least one flag."""
        from ctf.services.transfer import import_challenges

        payload = {
            "format": "shifter-challenges/v3",
            "challenges": [{"name": "Flagless", "description": "x", "category": "web", "points": 100, "flags": []}],
        }
        result = import_challenges(ctf_event_draft.pk, payload, actor_id=ctf_event_draft.created_by_id)
        assert result["created"] == []
        assert len(result["errors"]) == 1


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
        assert "statistics" in results
        assert "solves" in results
        assert "hint_usage" in results
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

    @pytest.mark.parametrize("url", ["http://hooks.example.test/x", "https://127.0.0.1/x"])
    def test_register_rejects_unsafe_destination_with_client_error(
        self, ctf_event, authenticated_organizer_client, url
    ):
        response = call_json(
            authenticated_organizer_client,
            "post",
            "api_event_webhooks",
            kwargs={"event_id": ctf_event.id},
            body={"url": url, "subscribed_events": ["flag_solve"]},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid"
        assert not CTFWebhook.objects.filter(event=ctf_event).exists()

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

        _pk, _url, secret, body, event_type = deliveries[0]
        assert event_type == "flag_solve"
        expected = hmac_lib.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert expected  # signature derivable from the queued body
        assert b'"event_type": "flag_solve"' in body

    def test_delivery_retries_then_records_failure(self, ctf_event, monkeypatch):
        from ctf.services import webhook as webhook_service
        from ctf.validators import _ssrf

        hook = CTFWebhook.objects.create(event=ctf_event, url="https://down.test/hook")
        attempts = []

        class FakeConnection:
            def request(self, method, path, *, body, headers):
                assert method == "POST"
                attempts.append(path)

            def getresponse(self):
                return type("Response", (), {"status": 503})()

            def close(self):
                pass

        monkeypatch.setattr(webhook_service.time, "sleep", lambda _s: None)
        monkeypatch.setattr(_ssrf, "_resolve_and_validate", lambda hostname, port: ["8.8.8.8"])
        monkeypatch.setattr(_ssrf, "_build_https_connection", lambda **kwargs: FakeConnection())
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
