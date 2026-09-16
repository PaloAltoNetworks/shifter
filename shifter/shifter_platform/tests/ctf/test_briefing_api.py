"""Per-event participant briefing surface (#1854).

Integration-style tests over the real DRF stack + DB (per the CTF test
convention: fixtures, not inline mocks). The briefing specializes the existing
``CTFEventPage`` concept under a reserved slug: organizer-authored, participant
read-only, event-scoped, sanitize-at-render (source stored verbatim).
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils import timezone

from ctf.models import CTFEventPage, CTFParticipant
from ctf.models.event import MAX_EVENT_PAGE_BODY_CHARS, RESERVED_BRIEFING_SLUG
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _enroll_active(user, event) -> Client:
    """Enrol ``user`` as an active participant of ``event`` and return their client."""
    from management.services import set_active_ctf_event

    CTFParticipant.objects.create(
        event=event,
        user=user,
        email=user.email,
        name="Reader",
        status="active",
        registered_at=timezone.now(),
    )
    set_active_ctf_event(user, event.pk)
    client = Client()
    client.force_login(user)
    return client


def _create_page(organizer_client, event, *, title, body, slug=None, order=0):
    payload = {"title": title, "body": body, "order": order}
    if slug is not None:
        payload["slug"] = slug
    return call_json(organizer_client, "post", "api_event_pages", kwargs={"event_id": event.id}, body=payload)


class TestBriefingRead:
    def test_present_returns_dto(self, ctf_event_active, participant_user, authenticated_organizer_client):
        created = _create_page(
            authenticated_organizer_client,
            ctf_event_active,
            title="Mission Briefing",
            body="You are on **Kali** inside Boreas Systems.",
            slug=RESERVED_BRIEFING_SLUG,
        )
        assert created.status_code == 201, created.content

        reader = _enroll_active(participant_user, ctf_event_active)
        resp = call_json(reader, "get", "api_me_briefing")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["slug"] == RESERVED_BRIEFING_SLUG
        assert body["body"] == "You are on **Kali** inside Boreas Systems."
        assert body["title"] == "Mission Briefing"

    def test_absent_returns_404(self, ctf_event_active, participant_user):
        reader = _enroll_active(participant_user, ctf_event_active)
        resp = call_json(reader, "get", "api_me_briefing")
        assert resp.status_code == 404

    def test_soft_deleted_briefing_falls_back(self, ctf_event_active, participant_user, authenticated_organizer_client):
        created = _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief", body="hi", slug=RESERVED_BRIEFING_SLUG
        )
        page_id = created.json()["id"]
        reader = _enroll_active(participant_user, ctf_event_active)
        assert call_json(reader, "get", "api_me_briefing").status_code == 200

        gone = call_json(authenticated_organizer_client, "delete", "api_event_page_detail", kwargs={"page_id": page_id})
        assert gone.status_code == 200
        assert call_json(reader, "get", "api_me_briefing").status_code == 404

    def test_source_stored_verbatim_not_sanitized_on_write(
        self, ctf_event_active, participant_user, authenticated_organizer_client
    ):
        # The decision is store-source / sanitize-at-render: the write path must
        # not mutate the Markdown source, so the render layer is the single
        # sanitization boundary. A hostile fragment round-trips unchanged.
        hostile = "Read this <script>alert(1)</script> then [go](javascript:alert(1))."
        _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief", body=hostile, slug=RESERVED_BRIEFING_SLUG
        )
        reader = _enroll_active(participant_user, ctf_event_active)
        resp = call_json(reader, "get", "api_me_briefing")
        assert resp.status_code == 200
        assert resp.json()["body"] == hostile


class TestReservedExclusion:
    def test_reserved_slug_excluded_from_me_pages(
        self, ctf_event_active, participant_user, authenticated_organizer_client
    ):
        _create_page(authenticated_organizer_client, ctf_event_active, title="Rules", body="be nice", slug="rules")
        _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief", body="brief", slug=RESERVED_BRIEFING_SLUG
        )
        reader = _enroll_active(participant_user, ctf_event_active)
        pages = call_json(reader, "get", "api_me_pages").json()["pages"]
        slugs = {p["slug"] for p in pages}
        assert "rules" in slugs
        assert RESERVED_BRIEFING_SLUG not in slugs


class TestScoping:
    def test_anonymous_cannot_read_briefing(self, ctf_event_active, authenticated_organizer_client):
        _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief", body="brief", slug=RESERVED_BRIEFING_SLUG
        )
        anon = Client()
        resp = call_json(anon, "get", "api_me_briefing")
        assert resp.status_code in (401, 403)

    def test_non_participant_is_denied(self, participant_user):
        # A CTF-group user who is not an active participant of any event cannot
        # reach a briefing: the participant permission layer denies the request
        # before the view, and no guidance is revealed.
        client = Client()
        client.force_login(participant_user)
        resp = call_json(client, "get", "api_me_briefing")
        assert resp.status_code in (403, 404)

    def test_briefing_is_scoped_to_active_event(
        self,
        ctf_event_active,
        ctf_event_draft,
        participant_user,
        second_participant_user,
        authenticated_organizer_client,
    ):
        from management.services import set_active_ctf_event

        # Briefing exists only on event B (draft).
        _create_page(
            authenticated_organizer_client,
            ctf_event_draft,
            title="Brief",
            body="secret brief",
            slug=RESERVED_BRIEFING_SLUG,
        )

        # Participant A is active on event A (no briefing) -> 404, never sees B's.
        CTFParticipant.objects.create(
            event=ctf_event_active,
            user=participant_user,
            email=participant_user.email,
            name="A",
            status="active",
            registered_at=timezone.now(),
        )
        set_active_ctf_event(participant_user, ctf_event_active.pk)
        client_a = Client()
        client_a.force_login(participant_user)
        assert call_json(client_a, "get", "api_me_briefing").status_code == 404

        # Participant B is active on event B (has briefing) -> 200.
        CTFParticipant.objects.create(
            event=ctf_event_draft,
            user=second_participant_user,
            email=second_participant_user.email,
            name="B",
            status="active",
            registered_at=timezone.now(),
        )
        set_active_ctf_event(second_participant_user, ctf_event_draft.pk)
        client_b = Client()
        client_b.force_login(second_participant_user)
        assert call_json(client_b, "get", "api_me_briefing").status_code == 200


class TestWriteBounds:
    def test_body_over_limit_rejected(self, ctf_event_active, authenticated_organizer_client):
        oversized = "x" * (MAX_EVENT_PAGE_BODY_CHARS + 1)
        resp = _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief", body=oversized, slug=RESERVED_BRIEFING_SLUG
        )
        assert resp.status_code == 400

    def test_body_at_limit_accepted(self, ctf_event_active, authenticated_organizer_client):
        at_limit = "x" * MAX_EVENT_PAGE_BODY_CHARS
        resp = _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief", body=at_limit, slug=RESERVED_BRIEFING_SLUG
        )
        assert resp.status_code == 201, resp.content

    def test_page_count_cap_enforced(self, ctf_event_active, authenticated_organizer_client, monkeypatch):
        monkeypatch.setattr("ctf.services.event.pages.MAX_EVENT_PAGES_PER_EVENT", 2)
        assert (
            _create_page(authenticated_organizer_client, ctf_event_active, title="A", body="a", slug="a").status_code
            == 201
        )
        assert (
            _create_page(authenticated_organizer_client, ctf_event_active, title="B", body="b", slug="b").status_code
            == 201
        )
        over = _create_page(authenticated_organizer_client, ctf_event_active, title="C", body="c", slug="c")
        assert over.status_code == 400


class TestDuplicateBriefing:
    def test_second_reserved_page_is_controlled_conflict_not_500(
        self, ctf_event_active, authenticated_organizer_client
    ):
        first = _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief", body="one", slug=RESERVED_BRIEFING_SLUG
        )
        assert first.status_code == 201
        second = _create_page(
            authenticated_organizer_client, ctf_event_active, title="Brief 2", body="two", slug=RESERVED_BRIEFING_SLUG
        )
        assert second.status_code == 400
        assert CTFEventPage.objects.filter(event=ctf_event_active, slug=RESERVED_BRIEFING_SLUG).count() == 1
