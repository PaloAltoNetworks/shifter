"""Platform-admin CTF authority: predicate, resolver, discovery, service gate (#1923, ADR-052).

Proves the superuser-only global override, its least-authority precedence behind
owner and delegated staff, authority-aware discovery, and the defense-in-depth
service gate. API-surface parity is covered in ``test_platform_admin_api.py``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ctf.enums import EventStatus
from ctf.exceptions import CTFPermissionError
from ctf.models import CTFEvent, CTFEventStaff
from ctf.services.authorization import (
    EventAuthoritySource,
    assert_actor_owns_event,
    is_ctf_platform_admin,
    resolve_event_authority,
)
from ctf.services.event._queries import resolve_administrable_events

pytestmark = pytest.mark.django_db

User = get_user_model()


def _event(owner, *, status=EventStatus.REGISTRATION.value, name="Owned Event") -> CTFEvent:
    now = timezone.now()
    return CTFEvent.objects.create(
        name=name,
        created_by=owner,
        status=status,
        event_start=now + timedelta(days=1),
        event_end=now + timedelta(days=1, hours=8),
        scenario_id="basic",
    )


@pytest.fixture
def superuser(db) -> User:
    return User.objects.create_superuser(username="root@test.com", email="root@test.com", password="rootpass123")  # nosec B106


class TestIsCtfPlatformAdmin:
    def test_active_superuser_is_admin(self, superuser):
        assert is_ctf_platform_admin(superuser) is True

    def test_inactive_superuser_is_not_admin(self, superuser):
        superuser.is_active = False
        superuser.save(update_fields=["is_active"])
        assert is_ctf_platform_admin(superuser) is False

    def test_staff_only_user_is_not_admin(self, standard_user):
        standard_user.is_staff = True
        standard_user.save(update_fields=["is_staff"])
        assert is_ctf_platform_admin(standard_user) is False

    def test_organizer_is_not_admin(self, organizer_user):
        assert is_ctf_platform_admin(organizer_user) is False

    def test_none_and_anonymous_are_not_admin(self):
        from django.contrib.auth.models import AnonymousUser

        assert is_ctf_platform_admin(None) is False
        assert is_ctf_platform_admin(AnonymousUser()) is False

    def test_temporary_ctf_account_superuser_denied_on_drift(self, superuser):
        """A marked temporary CTF account stays deny-authoritative even as superuser."""
        from management.services import get_user_profile

        profile = get_user_profile(superuser)
        profile.user_type = "ctf_participant"
        profile.is_ctf_account = True
        profile.cognito_sub = None
        profile.issuer = ""
        profile.save()
        superuser.refresh_from_db()
        assert is_ctf_platform_admin(superuser) is False


class TestResolveEventAuthority:
    def test_owner_resolves_owner(self, organizer_user):
        event = _event(organizer_user)
        assert resolve_event_authority(organizer_user, event) is EventAuthoritySource.OWNER

    def test_superuser_non_owner_resolves_platform_admin(self, organizer_user, superuser):
        event = _event(organizer_user)
        assert resolve_event_authority(superuser, event) is EventAuthoritySource.PLATFORM_ADMIN

    def test_owning_superuser_resolves_owner_not_admin(self, superuser):
        event = _event(superuser)
        assert resolve_event_authority(superuser, event) is EventAuthoritySource.OWNER

    def test_moderator_capability_resolves_event_staff(self, organizer_user, second_organizer_user):
        event = _event(organizer_user)
        CTFEventStaff.objects.create(event=event, user=second_organizer_user, role="moderator")
        assert resolve_event_authority(second_organizer_user, event, capability="participants") is (
            EventAuthoritySource.EVENT_STAFF
        )

    def test_staff_capability_precedes_platform_admin(self, organizer_user, superuser):
        """A superuser assigned as judge acts as staff for a granted capability (least authority).

        A live staff row grants authority only while the account holds the global
        CTF Organizer role (#1922 review — no stale-row bypass), which every real
        staff member does (``assign_event_staff`` requires it), so the superuser
        is made a CTF organizer here to exercise a realistic staff assignment.
        """
        from django.contrib.auth.models import Group

        from shared.auth import CTF_ORGANIZER_GROUP

        superuser.groups.add(Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0])
        event = _event(organizer_user)
        CTFEventStaff.objects.create(event=event, user=superuser, role="judge")
        assert resolve_event_authority(superuser, event, capability="awards") is EventAuthoritySource.EVENT_STAFF
        # ...but for an operation the judge role does not grant, the override applies.
        assert resolve_event_authority(superuser, event, capability="participants") is (
            EventAuthoritySource.PLATFORM_ADMIN
        )

    def test_unrelated_organizer_is_denied(self, organizer_user, second_organizer_user):
        event = _event(organizer_user)
        assert resolve_event_authority(second_organizer_user, event) is None
        assert resolve_event_authority(second_organizer_user, event, capability="participants") is None


class TestAssertActorOwnsEvent:
    def test_owner_passes(self, organizer_user):
        event = _event(organizer_user)
        assert_actor_owns_event(organizer_user.pk, event)  # no raise

    def test_platform_admin_passes(self, organizer_user, superuser):
        event = _event(organizer_user)
        assert_actor_owns_event(superuser.pk, event)  # no raise

    def test_unrelated_actor_raises(self, organizer_user, second_organizer_user):
        event = _event(organizer_user)
        with pytest.raises(CTFPermissionError):
            assert_actor_owns_event(second_organizer_user.pk, event)


class TestAuthorityAwareDiscovery:
    def test_platform_admin_sees_all_live_events(self, organizer_user, second_organizer_user, superuser):
        a = _event(organizer_user, name="A")
        b = _event(second_organizer_user, name="B")
        archived = _event(organizer_user, name="Archived", status=EventStatus.ARCHIVED.value)
        tombstone = _event(second_organizer_user, name="Deleted")
        tombstone.delete(soft=True)

        ids = set(resolve_administrable_events(superuser).values_list("id", flat=True))
        assert {a.id, b.id, archived.id} <= ids
        assert tombstone.id not in ids

    def test_organizer_sees_owned_plus_staff_assigned(self, organizer_user, second_organizer_user):
        owned = _event(organizer_user, name="Owned")
        other = _event(second_organizer_user, name="Other")
        assigned = _event(second_organizer_user, name="Assigned")
        CTFEventStaff.objects.create(event=assigned, user=organizer_user, role="moderator")

        ids = set(resolve_administrable_events(organizer_user).values_list("id", flat=True))
        assert ids == {owned.id, assigned.id}
        assert other.id not in ids

    def test_revoked_staff_assignment_drops_from_discovery(self, organizer_user, second_organizer_user):
        assigned = _event(second_organizer_user, name="Assigned")
        staff = CTFEventStaff.objects.create(event=assigned, user=organizer_user, role="moderator")
        staff.delete(soft=True)

        ids = set(resolve_administrable_events(organizer_user).values_list("id", flat=True))
        assert assigned.id not in ids

    def test_no_duplicate_rows_when_owner_and_staff(self, organizer_user):
        """An owner who is also a staff row on their own event appears once."""
        owned = _event(organizer_user, name="Owned")
        CTFEventStaff.objects.create(event=owned, user=organizer_user, role="judge")
        ids = list(resolve_administrable_events(organizer_user).values_list("id", flat=True))
        assert ids.count(owned.id) == 1
