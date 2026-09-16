"""Platform-admin CTF administration through the canonical DRF API (#1923, ADR-052).

Exercises the organizer-or-platform-admin admission gate, authority-aware
discovery, detail/mutation parity, the override audit trail, and the negative
cases (unrelated organizer, standard user, staff management stays owner-only).
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group

from shared.auth import CTF_ORGANIZER_GROUP
from shared.models import AuditLog
from tests.ctf._api_flow_helpers import call_json

pytestmark = pytest.mark.django_db


def _make_organizer(email: str):
    from django.contrib.auth.models import User

    from management.services import get_user_profile

    Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
    user = User.objects.create_user(username=email, email=email, password="testpass123")  # nosec B106
    group, _ = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)
    user.groups.add(group)
    profile = get_user_profile(user)
    profile.user_type = "ctf_organizer"
    profile.save(update_fields=["user_type"])
    return user


@pytest.fixture
def superuser_client(admin_user):
    from django.test import Client

    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def other_event(second_organizer_user):
    """An event owned by a different organizer than ``ctf_event``."""
    from datetime import timedelta

    from django.utils import timezone

    from ctf.enums import EventStatus
    from ctf.models import CTFEvent

    now = timezone.now()
    return CTFEvent.objects.create(
        name="Other Org Event",
        created_by=second_organizer_user,
        status=EventStatus.REGISTRATION.value,
        event_start=now + timedelta(days=1),
        event_end=now + timedelta(days=1, hours=8),
        scenario_id="basic",
    )


class TestAdmission:
    def test_standard_user_is_forbidden(self, authenticated_standard_client, ctf_event):
        resp = call_json(authenticated_standard_client, "get", "api_event_list")
        assert resp.status_code == 403

    def test_superuser_is_admitted(self, superuser_client, ctf_event):
        assert call_json(superuser_client, "get", "api_event_list").status_code == 200


class TestDiscovery:
    def test_superuser_lists_all_events_with_owner_and_source(self, superuser_client, ctf_event, other_event):
        resp = call_json(superuser_client, "get", "api_event_list")
        assert resp.status_code == 200
        events = {e["id"]: e for e in resp.json()["events"]}
        assert {str(ctf_event.id), str(other_event.id)} <= set(events)
        row = events[str(other_event.id)]
        assert row["access_source"] == "platform_admin"
        assert row["owner"]["id"] == str(other_event.created_by_id)
        assert row["owner"]["display_name"]

    def test_organizer_sees_only_owned(self, authenticated_organizer_client, ctf_event, other_event):
        resp = call_json(authenticated_organizer_client, "get", "api_event_list")
        ids = {e["id"] for e in resp.json()["events"]}
        assert str(ctf_event.id) in ids
        assert str(other_event.id) not in ids

    def test_owner_row_reports_owner_source(self, authenticated_organizer_client, ctf_event):
        resp = call_json(authenticated_organizer_client, "get", "api_event_list")
        row = next(e for e in resp.json()["events"] if e["id"] == str(ctf_event.id))
        assert row["access_source"] == "owner"

    def test_status_filter_rejects_unknown_value(self, superuser_client, ctf_event):
        resp = call_json(superuser_client, "get", "api_event_list", query="?status=bogus")
        assert resp.status_code == 400


class TestDetailAndMutation:
    def test_superuser_reads_other_event_detail(self, superuser_client, other_event):
        resp = call_json(superuser_client, "get", "api_event_detail", kwargs={"event_id": other_event.id})
        assert resp.status_code == 200
        assert resp.json()["access_source"] == "platform_admin"

    def test_unrelated_organizer_denied_detail(self, authenticated_organizer_client, other_event):
        resp = call_json(authenticated_organizer_client, "get", "api_event_detail", kwargs={"event_id": other_event.id})
        assert resp.status_code == 403

    def test_superuser_updates_other_event_and_audits(self, superuser_client, other_event):
        original_owner_id = other_event.created_by_id
        resp = call_json(
            superuser_client,
            "put",
            "api_event_detail",
            kwargs={"event_id": other_event.id},
            body={"name": "Renamed By Admin"},
        )
        assert resp.status_code == 200
        other_event.refresh_from_db()
        assert other_event.name == "Renamed By Admin"
        assert other_event.created_by_id == original_owner_id  # ownership unchanged

        record = AuditLog.objects.filter(context="ctf_platform_admin_event_action").order_by("-timestamp").first()
        assert record is not None
        assert record.new_state["authority_source"] == "platform_admin"
        assert record.new_state["operation"] == "event.update"
        assert record.new_state["event_id"] == str(other_event.id)

    def test_owner_update_does_not_write_admin_audit(self, authenticated_organizer_client, ctf_event):
        resp = call_json(
            authenticated_organizer_client,
            "put",
            "api_event_detail",
            kwargs={"event_id": ctf_event.id},
            body={"name": "Owner Rename"},
        )
        assert resp.status_code == 200
        assert not AuditLog.objects.filter(context="ctf_platform_admin_event_action").exists()

    def test_superuser_lifecycle_transition_audited(self, superuser_client, other_event):
        resp = call_json(
            superuser_client,
            "post",
            "api_event_lifecycle",
            kwargs={"event_id": other_event.id},
            body={"action": "activate"},
        )
        assert resp.status_code == 200
        assert AuditLog.objects.filter(
            context="ctf_platform_admin_event_action",
            new_state__operation="event.lifecycle.activate",
        ).exists()


class TestNestedMutationOverrideAudit:
    """Nested event-derived mutations via the override capture the source and audit (ADR-052-R4)."""

    @pytest.fixture
    def other_challenge(self, other_event):
        from ctf.models import CTFChallenge, CTFFlag
        from ctf.services.challenge import hash_flag

        challenge = CTFChallenge.objects.create(
            event=other_event,
            name="Nested Challenge",
            description="d",
            category="web",
            points=100,
            difficulty="easy",
            flag_format="FLAG{...}",
        )
        CTFFlag.objects.create(challenge=challenge, flag_hash=hash_flag("FLAG{x}"), flag_type="static", order=0)
        return challenge

    def test_superuser_challenge_create_is_audited(self, superuser_client, other_event):
        resp = call_json(
            superuser_client,
            "post",
            "api_challenge_list",
            kwargs={"event_id": other_event.id},
            body={"name": "Admin Challenge", "description": "d", "flag": "FLAG{a}", "points": 50, "category": "web"},
        )
        assert resp.status_code == 201
        assert AuditLog.objects.filter(
            context="ctf_platform_admin_event_action",
            new_state__operation="challenge.create",
        ).exists()

    def test_superuser_flag_delete_is_audited(self, superuser_client, other_challenge):
        flag_id = other_challenge.flags.first().id
        resp = call_json(superuser_client, "post", "api_remove_flag", kwargs={"flag_id": flag_id})
        assert resp.status_code == 200
        assert AuditLog.objects.filter(
            context="ctf_platform_admin_event_action",
            new_state__operation="flag.delete",
        ).exists()

    def test_owner_nested_mutation_writes_no_admin_audit(self, authenticated_organizer_client, ctf_event):
        resp = call_json(
            authenticated_organizer_client,
            "post",
            "api_challenge_list",
            kwargs={"event_id": ctf_event.id},
            body={"name": "Owner Challenge", "description": "d", "flag": "FLAG{o}", "points": 50, "category": "web"},
        )
        assert resp.status_code == 201
        assert not AuditLog.objects.filter(context="ctf_platform_admin_event_action").exists()


class TestBootstrapAdvisoryFlag:
    _URL = "/api/v1/bootstrap/"

    def test_superuser_can_administer_ctf(self, superuser_client):
        perms = superuser_client.get(self._URL).json()["permissions"]
        assert perms["can_administer_ctf"] is True
        assert perms["is_ctf_organizer"] is False

    def test_organizer_can_administer_ctf(self, authenticated_organizer_client):
        perms = authenticated_organizer_client.get(self._URL).json()["permissions"]
        assert perms["can_administer_ctf"] is True

    def test_standard_user_cannot_administer_ctf(self, authenticated_standard_client):
        perms = authenticated_standard_client.get(self._URL).json()["permissions"]
        assert perms["can_administer_ctf"] is False


class TestStaffManagementViaOverride:
    """Staff management is owner-or-platform-admin (ADR-052-R2), audited, never delegable to staff."""

    def test_superuser_assigns_staff_and_audits(self, superuser_client, other_event, organizer_user):
        from ctf.models import CTFEventStaff

        original_owner_id = other_event.created_by_id
        resp = call_json(
            superuser_client,
            "post",
            "api_event_staff",
            kwargs={"event_id": other_event.id},
            body={"email": organizer_user.email, "role": "moderator"},
        )
        assert resp.status_code == 201
        assert CTFEventStaff.objects.filter(
            event=other_event, user=organizer_user, role="moderator", deleted_at__isnull=True
        ).exists()
        # The override never became owner, and the mutation is audited.
        other_event.refresh_from_db()
        assert other_event.created_by_id == original_owner_id
        assert AuditLog.objects.filter(
            context="ctf_platform_admin_event_action",
            new_state__operation="staff.assign",
        ).exists()

    def test_unrelated_organizer_cannot_assign_staff(self, other_event, second_organizer_user):
        """A non-owner organizer with no override is refused (authorization, not validation)."""
        from django.test import Client

        # A third organizer, neither owner nor platform admin.
        outsider = _make_organizer("outsider@test.com")
        client = Client()
        client.force_login(outsider)
        resp = call_json(
            client,
            "post",
            "api_event_staff",
            kwargs={"event_id": other_event.id},
            body={"email": second_organizer_user.email, "role": "moderator"},
        )
        assert resp.status_code in (400, 403)


class TestEventCreationAuthority:
    """Event creation is organizer authority, never the platform-admin override (ADR-052)."""

    def test_pure_superuser_cannot_create_event(self, superuser_client):
        resp = call_json(
            superuser_client,
            "post",
            "api_event_list",
            body={
                "name": "Admin Event",
                "event_start": "2099-01-01T00:00:00Z",
                "event_end": "2099-01-02T00:00:00Z",
            },
        )
        assert resp.status_code == 403
        from ctf.models import CTFEvent

        assert not CTFEvent.objects.filter(name="Admin Event").exists()

    def test_organizer_can_still_create_event(self, authenticated_organizer_client):
        resp = call_json(
            authenticated_organizer_client,
            "post",
            "api_event_list",
            body={
                "name": "Organizer Event",
                "event_start": "2099-01-01T00:00:00Z",
                "event_end": "2099-01-02T00:00:00Z",
            },
        )
        assert resp.status_code == 201
