"""Full co-organizer role: capabilities, listings, ownership transfer, audit (#1922).

A co-organizer holds every operational event capability the owner has
(configuration, challenges, participants, lifecycle, content, ...) but never the
owner-only authority-topology operations (staff management, ownership transfer).
The owner remains the single canonical ``CTFEvent.created_by``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from shared.auth import CTF_ORGANIZER_GROUP
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _organizer(email: str) -> User:
    from management.services import get_user_profile

    user = User.objects.create_user(username=email, email=email, password="testpass123")  # nosec B106
    group, _ = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
    user.groups.add(group)
    profile = get_user_profile(user)
    profile.user_type = "ctf_organizer"
    profile.save(update_fields=["user_type"])
    return user


def _client_for(user: User) -> Client:
    fresh = Client()
    fresh.force_login(user)
    return fresh


def _assign(client, event, email, role):
    return call_json(
        client, "post", "api_event_staff", kwargs={"event_id": event.id}, body={"email": email, "role": role}
    )


@pytest.fixture
def co_organizer_user():
    return _organizer("coorg@test.com")


@pytest.fixture
def co_organizer_client(co_organizer_user):
    return _client_for(co_organizer_user)


@pytest.fixture
def co_organized_event(ctf_event, authenticated_organizer_client, co_organizer_user):
    """The base event with ``coorg@test.com`` assigned as a full co-organizer."""
    resp = _assign(authenticated_organizer_client, ctf_event, "coorg@test.com", "co_organizer")
    assert resp.status_code == 201, resp.content
    return ctf_event


class TestCoOrganizerAssignment:
    def test_owner_assigns_co_organizer(self, ctf_event, authenticated_organizer_client, co_organizer_user):
        resp = _assign(authenticated_organizer_client, ctf_event, "coorg@test.com", "co_organizer")
        assert resp.status_code == 201
        assert resp.json()["role"] == "co_organizer"

    def test_co_organizer_role_is_valid(self):
        from ctf.enums import EventStaffRole

        assert EventStaffRole.CO_ORGANIZER.value == "co_organizer"


class TestCoOrganizerCapabilities:
    """A co-organizer exercises the full operational surface the owner has."""

    def test_manages_challenges(self, co_organized_event, co_organizer_client):
        listing = call_json(
            co_organizer_client, "get", "api_challenge_list", kwargs={"event_id": co_organized_event.id}
        )
        assert listing.status_code == 200
        created = call_json(
            co_organizer_client,
            "post",
            "api_challenge_list",
            kwargs={"event_id": co_organized_event.id},
            body={
                "name": "Co-org challenge",
                "description": "d",
                "category": "web",
                "points": 100,
                "flag": "flag{co_org}",
            },
        )
        assert created.status_code == 201

    def test_reads_event_config_detail(self, co_organized_event, co_organizer_client):
        detail = call_json(co_organizer_client, "get", "api_event_detail", kwargs={"event_id": co_organized_event.id})
        assert detail.status_code == 200

    def test_reads_lifecycle_task_surface(self, co_organized_event, co_organizer_client):
        tasks = call_json(co_organizer_client, "get", "api_event_tasks", kwargs={"event_id": co_organized_event.id})
        assert tasks.status_code == 200

    def test_manages_participants(self, co_organized_event, co_organizer_client, monkeypatch):
        monkeypatch.setattr("ctf.services.participant.accounts.request_event_provisioning", lambda *_a, **_kw: None)
        roster = call_json(
            co_organizer_client, "get", "api_participant_list", kwargs={"event_id": co_organized_event.id}
        )
        assert roster.status_code == 200

    def test_cannot_manage_staff(self, co_organized_event, co_organizer_client):
        """Authority topology stays owner-only: co-organizers cannot list/assign staff."""
        listing = call_json(co_organizer_client, "get", "api_event_staff", kwargs={"event_id": co_organized_event.id})
        assert listing.status_code == 403
        assign = _assign(co_organizer_client, co_organized_event, "coorg@test.com", "moderator")
        assert assign.status_code == 403


class TestCoOrganizerDestructive:
    """Co-organizers perform destructive ops (with safeguards); bounded roles cannot."""

    def test_co_organizer_can_soft_delete_event(self, co_organized_event, co_organizer_client):
        resp = call_json(co_organizer_client, "delete", "api_event_detail", kwargs={"event_id": co_organized_event.id})
        assert resp.status_code == 204

    def test_moderator_cannot_soft_delete_event(self, ctf_event, authenticated_organizer_client, co_organizer_user):
        _assign(authenticated_organizer_client, ctf_event, "coorg@test.com", "moderator")
        resp = call_json(
            _client_for(co_organizer_user), "delete", "api_event_detail", kwargs={"event_id": ctf_event.id}
        )
        assert resp.status_code == 403


class TestBoundedRolesUnchanged:
    """Moderator/judge remain strictly bounded; only co-organizer gets full access."""

    def test_moderator_still_cannot_manage_challenges(
        self, ctf_event, authenticated_organizer_client, co_organizer_user
    ):
        _assign(authenticated_organizer_client, ctf_event, "coorg@test.com", "moderator")
        client = _client_for(co_organizer_user)
        challenges = call_json(client, "get", "api_challenge_list", kwargs={"event_id": ctf_event.id})
        assert challenges.status_code == 403


class TestCoOrganizerListing:
    def test_co_organized_event_appears_in_listing(self, co_organized_event, co_organizer_client):
        listing = call_json(co_organizer_client, "get", "api_event_list")
        assert listing.status_code == 200
        ids = {e["id"] for e in listing.json()["events"]}
        assert str(co_organized_event.id) in ids

    def test_unrelated_organizer_does_not_see_event(self, co_organized_event):
        stranger = _organizer("stranger@test.com")
        listing = call_json(_client_for(stranger), "get", "api_event_list")
        ids = {e["id"] for e in listing.json()["events"]}
        assert str(co_organized_event.id) not in ids

    def test_removed_co_organizer_loses_listing_and_access(
        self, co_organized_event, authenticated_organizer_client, co_organizer_client, co_organizer_user
    ):
        revoke = call_json(
            authenticated_organizer_client,
            "delete",
            "api_event_staff_member",
            kwargs={"event_id": co_organized_event.id, "user_id": co_organizer_user.pk},
        )
        assert revoke.status_code == 200
        listing = call_json(co_organizer_client, "get", "api_event_list")
        ids = {e["id"] for e in listing.json()["events"]}
        assert str(co_organized_event.id) not in ids
        challenges = call_json(
            co_organizer_client, "get", "api_challenge_list", kwargs={"event_id": co_organized_event.id}
        )
        assert challenges.status_code == 403


class TestAccessProjection:
    """Server-derived access_source / access_capabilities hints (#1922, ADR-052)."""

    def test_owner_projection(self, co_organized_event, authenticated_organizer_client):
        detail = call_json(
            authenticated_organizer_client, "get", "api_event_detail", kwargs={"event_id": co_organized_event.id}
        )
        body = detail.json()
        assert body["access_source"] == "owner"
        assert "delete" in body["access_capabilities"]

    def test_co_organizer_projection(self, co_organized_event, co_organizer_client):
        detail = call_json(co_organizer_client, "get", "api_event_detail", kwargs={"event_id": co_organized_event.id})
        body = detail.json()
        # A co-organizer reaches the event through a live staff row; the advisory
        # capability set is the full co-organizer grant.
        assert body["access_source"] == "event_staff"
        assert "challenges" in body["access_capabilities"]

    def test_listing_carries_access_source(self, co_organized_event, co_organizer_client):
        listing = call_json(co_organizer_client, "get", "api_event_list")
        entry = next(e for e in listing.json()["events"] if e["id"] == str(co_organized_event.id))
        assert entry["access_source"] == "event_staff"
        assert "challenges" in entry["access_capabilities"]


class TestOwnershipTransfer:
    def _transfer(self, client, event, new_owner_id):
        return call_json(
            client,
            "post",
            "api_event_transfer_ownership",
            kwargs={"event_id": event.id},
            body={"user_id": new_owner_id},
        )

    def test_owner_transfers_to_co_organizer(
        self, co_organized_event, authenticated_organizer_client, co_organizer_user, organizer_user
    ):
        resp = self._transfer(authenticated_organizer_client, co_organized_event, co_organizer_user.pk)
        assert resp.status_code == 200, resp.content
        co_organized_event.refresh_from_db()
        assert co_organized_event.created_by_id == co_organizer_user.pk
        # Previous owner retained as a co-organizer (non-null owner invariant preserved).
        from ctf.models import CTFEventStaff

        prev = CTFEventStaff.objects.filter(
            event=co_organized_event, user=organizer_user, deleted_at__isnull=True
        ).first()
        assert prev is not None
        assert prev.role == "co_organizer"
        # New owner no longer carries a redundant staff row.
        assert not CTFEventStaff.objects.filter(
            event=co_organized_event, user=co_organizer_user, deleted_at__isnull=True
        ).exists()

    def test_transfer_target_must_be_live_co_organizer(
        self, ctf_event, authenticated_organizer_client, co_organizer_user
    ):
        # coorg is a valid organizer but NOT assigned to this event.
        resp = self._transfer(authenticated_organizer_client, ctf_event, co_organizer_user.pk)
        assert resp.status_code == 400

    def test_co_organizer_cannot_transfer(self, co_organized_event, co_organizer_client, co_organizer_user):
        resp = self._transfer(co_organizer_client, co_organized_event, co_organizer_user.pk)
        assert resp.status_code == 403

    def test_previous_owner_keeps_full_access_after_transfer(
        self, co_organized_event, authenticated_organizer_client, co_organizer_user, organizer_user
    ):
        self._transfer(authenticated_organizer_client, co_organized_event, co_organizer_user.pk)
        # Former owner (now co-organizer) still manages challenges...
        prev_owner_client = _client_for(organizer_user)
        challenges = call_json(
            prev_owner_client, "get", "api_challenge_list", kwargs={"event_id": co_organized_event.id}
        )
        assert challenges.status_code == 200
        # ...but can no longer manage staff (owner-only now belongs to the new owner).
        staff = call_json(prev_owner_client, "get", "api_event_staff", kwargs={"event_id": co_organized_event.id})
        assert staff.status_code == 403


class TestCoOrganizerRealtime:
    """Realtime authorization is consistent: co-organizers subscribe and receive (#1922)."""

    def test_co_organizer_can_subscribe(self, co_organized_event, co_organizer_user):
        from ctf.services.notification.realtime import _can_subscribe, event_topic

        assert _can_subscribe(co_organizer_user, event_topic(co_organized_event.id)) is True

    def test_removed_co_organizer_cannot_subscribe(
        self, co_organized_event, authenticated_organizer_client, co_organizer_user
    ):
        from ctf.services.notification.realtime import _can_subscribe, event_topic

        call_json(
            authenticated_organizer_client,
            "delete",
            "api_event_staff_member",
            kwargs={"event_id": co_organized_event.id, "user_id": co_organizer_user.pk},
        )
        assert _can_subscribe(co_organizer_user, event_topic(co_organized_event.id)) is False

    def test_default_recipients_include_owner_and_co_organizer(
        self, co_organized_event, organizer_user, co_organizer_user, monkeypatch
    ):
        captured: dict[str, object] = {}

        def _capture(_type, *, topic, payload, recipient_ids, event_id):
            captured["recipient_ids"] = recipient_ids

        monkeypatch.setattr("shared.notifications.notifications_enabled", lambda: True)
        monkeypatch.setattr("shared.notifications.publish_notification", _capture)
        from ctf.services.notification.realtime import publish_event_notification

        publish_event_notification(co_organized_event, "test", {})
        recipients = captured["recipient_ids"]
        assert organizer_user.pk in recipients
        assert co_organizer_user.pk in recipients
        # De-duplicated.
        assert len(recipients) == len(set(recipients))


class TestAuthorityMutationsAreAudited:
    def test_assignment_and_transfer_write_audit(self, ctf_event, authenticated_organizer_client, co_organizer_user):
        from shared.models import AuditLog

        _assign(authenticated_organizer_client, ctf_event, "coorg@test.com", "co_organizer")
        assert AuditLog.objects.filter(context__icontains="ctf_event_staff").exists()

        call_json(
            authenticated_organizer_client,
            "post",
            "api_event_transfer_ownership",
            kwargs={"event_id": ctf_event.id},
            body={"user_id": co_organizer_user.pk},
        )
        assert AuditLog.objects.filter(context__icontains="ctf_event_ownership_transfer").exists()


class TestReviewFindingRegressions:
    """Locks the codex cycle-1 findings (#1922 review): fixes stay fixed."""

    def test_unknown_capability_fails_closed_even_for_owner(self, ctf_event, organizer_user):
        """F3: an unknown/misspelled capability denies for everyone, owner included."""
        from ctf.enums import EventCapability
        from ctf.services.authorization import resolve_event_authority

        assert resolve_event_authority(organizer_user, ctf_event, capability=EventCapability.CONFIG.value) is not None
        assert resolve_event_authority(organizer_user, ctf_event, capability="bogus_capability") is None

    def test_transfer_rejects_ineligible_target(
        self, co_organized_event, authenticated_organizer_client, co_organizer_user, organizer_user
    ):
        """F2: a co-organizer deactivated after assignment cannot receive ownership."""
        co_organizer_user.is_active = False
        co_organizer_user.save(update_fields=["is_active"])
        resp = call_json(
            authenticated_organizer_client,
            "post",
            "api_event_transfer_ownership",
            kwargs={"event_id": co_organized_event.id},
            body={"user_id": co_organizer_user.pk},
        )
        assert resp.status_code == 400
        co_organized_event.refresh_from_db()
        assert co_organized_event.created_by_id == organizer_user.pk  # ownership unchanged

    def test_delete_event_service_asserts_capability(self, ctf_event, participant_user):
        """F1: the delete command enforces the capability at the service boundary."""
        from ctf.exceptions import CTFPermissionError
        from ctf.services import delete_event

        with pytest.raises(CTFPermissionError):
            delete_event(ctf_event.id, actor_id=participant_user.pk)
        # System path (no actor) remains a trusted operation.
        delete_event(ctf_event.id)

    def test_provisioning_service_asserts_for_interactive_actor(self, ctf_event, participant_user):
        """F1: manual provisioning enforces the capability at the service boundary."""
        from ctf.exceptions import CTFPermissionError
        from ctf.services.range import request_event_provisioning

        with pytest.raises(CTFPermissionError):
            request_event_provisioning(ctf_event.id, source="manual", actor_id=participant_user.pk)


def _demote(user: User) -> None:
    """Strip the global CTF Organizer role from ``user`` (keeps the account active)."""
    group = Group.objects.get(name=CTF_ORGANIZER_GROUP)
    user.groups.remove(group)


class TestReviewCycle2Regressions:
    """Locks the codex cycle-2 findings (#1922 review): fixes stay fixed."""

    def test_resolver_denies_unknown_capability_for_owner(self, ctf_event, organizer_user):
        """C2-F1: the authority resolver fails closed on an unknown capability, owner included."""
        from ctf.enums import EventCapability
        from ctf.services.authorization import resolve_event_authority

        assert resolve_event_authority(organizer_user, ctf_event, capability="bogus_capability") is None
        assert resolve_event_authority(organizer_user, ctf_event, capability=EventCapability.CONFIG) is not None

    def test_resolver_tuple_selector_admits_co_organizer(self, co_organized_event, co_organizer_user):
        """C2-F1: a tuple selector is evaluated per-alternative, not stringified."""
        from ctf.enums import EventCapability
        from ctf.services.authorization import resolve_event_authority

        source = resolve_event_authority(
            co_organizer_user,
            co_organized_event,
            capability=(EventCapability.CHALLENGES, EventCapability.CONFIG),
        )
        assert source is not None

    def test_idempotent_reassign_writes_no_new_audit(
        self, ctf_event, authenticated_organizer_client, co_organizer_user
    ):
        """C2-F2: re-submitting the current role performs no write and no audit event."""
        from shared.models import AuditLog

        _assign(authenticated_organizer_client, ctf_event, "coorg@test.com", "co_organizer")
        baseline = AuditLog.objects.filter(context__icontains="ctf_event_staff").count()
        resp = _assign(authenticated_organizer_client, ctf_event, "coorg@test.com", "co_organizer")
        assert resp.status_code == 201  # idempotent success
        assert AuditLog.objects.filter(context__icontains="ctf_event_staff").count() == baseline

    def test_demoted_co_organizer_loses_capability(self, co_organized_event, co_organizer_user):
        """C2-F3: a stale staff row does not grant authority after global-role revocation."""
        from ctf.enums import EventCapability
        from ctf.services.authorization import resolve_event_authority

        cap = EventCapability.CHALLENGES.value
        assert resolve_event_authority(co_organizer_user, co_organized_event, capability=cap) is not None
        _demote(co_organizer_user)
        assert resolve_event_authority(co_organizer_user, co_organized_event, capability=cap) is None

    def test_demoted_co_organizer_denied_participants_scoreboard(self, co_organized_event, co_organizer_user, rf):
        """C2-F3: the public participants-only scoreboard rechecks current eligibility."""
        from ctf.api.views import _scoreboard_access_allowed
        from ctf.enums import ScoreboardVisibility

        co_organized_event.scoreboard_visibility = ScoreboardVisibility.PARTICIPANTS.value
        eligible_req = rf.get("/")
        eligible_req.user = co_organizer_user
        assert _scoreboard_access_allowed(co_organized_event, eligible_req) is True
        _demote(co_organizer_user)
        demoted_req = rf.get("/")
        demoted_req.user = co_organizer_user
        assert _scoreboard_access_allowed(co_organized_event, demoted_req) is False

    def test_demoted_co_organizer_cannot_subscribe(self, co_organized_event, co_organizer_user):
        """C2-F3: realtime subscription rechecks current eligibility."""
        from ctf.services.notification.realtime import _can_subscribe, event_topic

        assert _can_subscribe(co_organizer_user, event_topic(co_organized_event.id)) is True
        _demote(co_organizer_user)
        assert _can_subscribe(co_organizer_user, event_topic(co_organized_event.id)) is False

    def test_recipient_projection_excludes_demoted_co_organizer(self, co_organized_event, co_organizer_user):
        """C2-F3: the organizer-recipient projection drops demoted accounts."""
        from ctf.services.event.staff import eligible_co_organizer_ids

        assert co_organizer_user.pk in eligible_co_organizer_ids(co_organized_event)
        _demote(co_organizer_user)
        assert co_organizer_user.pk not in eligible_co_organizer_ids(co_organized_event)


class TestReviewCycle3Regressions:
    """Locks the codex cycle-3 class finding (#1922): mutation boundaries assert the capability."""

    def test_update_event_service_asserts_capability(self, ctf_event, participant_user):
        """C3-F1: event config update enforces the capability at the service boundary."""
        from ctf.exceptions import CTFPermissionError
        from ctf.services import update_event

        with pytest.raises(CTFPermissionError):
            update_event(ctf_event.id, {"name": "Renamed"}, actor_id=participant_user.pk)

    def test_lifecycle_transition_service_asserts_capability(self, ctf_event, participant_user):
        """C3-F1: interactive lifecycle transition enforces the capability at the service boundary."""
        from ctf.exceptions import CTFPermissionError
        from ctf.services.event import apply_event_lifecycle_transition

        with pytest.raises(CTFPermissionError):
            apply_event_lifecycle_transition(ctf_event, "activate", actor_id=participant_user.pk)

    def test_webhook_delete_service_asserts_capability(self, ctf_event, participant_user):
        """C3-F1: webhook deletion enforces the capability at the service boundary, not the view."""
        from ctf.exceptions import CTFPermissionError
        from ctf.models import CTFWebhook
        from ctf.services.webhook import delete_event_webhook

        hook = CTFWebhook.objects.create(
            event=ctf_event, url="https://example.test/hook", secret="", subscribed_events=[]
        )
        with pytest.raises(CTFPermissionError):
            delete_event_webhook(hook.id, actor_id=participant_user.pk)
