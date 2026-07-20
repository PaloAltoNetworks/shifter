"""Behavior tests for the centralized user-type sync helper (config/user_type_sync.py).

The helper is the single point where a self-mutable ``custom:user_type`` value
turns into CTF group membership, and the safety control for issue #937 SEC-5 is
that every resulting change is recorded in a durable, reviewable audit row. The
tests drive the real helper against real users, groups, profiles, and
``AuditLog`` rows and assert on the persisted membership and audit trail.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from config.user_type_sync import USER_TYPE_TO_GROUP, sync_user_type
from management.services import get_user_profile
from risk_register.models import AuditLog
from shared.audit import (
    AuditAction,
    AuditEntityType,
)
from shared.auth import (
    CTF_ORGANIZER_GROUP,
    CTF_PARTICIPANT_GROUP,
    THREAT_RESEARCH_GROUP,
    can_edit_cms_authoring,
)

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="u@example.com", email="u@example.com")


def _group_names(user) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def _role_sync_rows(user):
    return AuditLog.objects.filter(
        entity_type=AuditEntityType.USER,
        entity_id=user.id,
        action=AuditAction.ROLE_SYNC,
    )


@pytest.mark.django_db
class TestSyncUserType:
    def test_participant_claim_grants_participant_group_and_audits(self, user):
        sync_user_type(user, "ctf_participant", source="oidc")

        assert _group_names(user) == {CTF_PARTICIPANT_GROUP}
        assert get_user_profile(user).user_type == "ctf_participant"
        row = _role_sync_rows(user).get()
        assert row.previous_state["user_type"] == "standard"
        assert row.new_state["user_type"] == "ctf_participant"
        assert row.new_state["groups"] == [CTF_PARTICIPANT_GROUP]

    def test_organizer_claim_does_not_grant_organizer_group(self, user):
        # #1516: CTF Organizer authority must never come from the self-mutable
        # user_type claim. An organizer claim is inert on this path — no group is
        # added and no audit row is written.
        sync_user_type(user, "ctf_organizer", source="oidc")
        assert _group_names(user) == set()
        assert _role_sync_rows(user).count() == 0

    def test_standard_claim_removes_ctf_groups(self, user):
        user.groups.add(Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)[0])
        sync_user_type(user, "standard", source="oidc")
        assert _group_names(user) == set()
        assert _role_sync_rows(user).count() == 1

    def test_participant_sync_preserves_admin_granted_organizer_group(self, user):
        # #1516: organizer is admin-controlled. A dual-role user (admin-granted
        # organizer who also self-registers as a participant) keeps organizer; the
        # self-service participant sync adds its own group without touching it.
        user.groups.add(Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0])
        sync_user_type(user, "ctf_participant", source="oidc")
        assert _group_names(user) == {CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP}

    def test_standard_claim_clears_participant_but_not_admin_organizer(self, user):
        # #1516: ``standard`` drops the self-service participant group but must
        # never remove an admin-granted organizer group — self-service identity
        # data cannot alter organizer authority in either direction.
        user.groups.add(Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0])
        sync_user_type(user, "ctf_participant", source="oidc")
        sync_user_type(user, "standard", source="oidc")
        assert _group_names(user) == {CTF_ORGANIZER_GROUP}

    def test_no_op_when_already_in_target_state_writes_no_audit_row(self, user):
        sync_user_type(user, "ctf_participant", source="oidc")
        before = _role_sync_rows(user).count()
        sync_user_type(user, "ctf_participant", source="oidc")
        assert _role_sync_rows(user).count() == before

    def test_invalid_claim_makes_no_change_and_no_audit(self, user):
        sync_user_type(user, "platform_admin", source="oidc")
        assert _group_names(user) == set()
        assert get_user_profile(user).user_type == "standard"
        assert _role_sync_rows(user).count() == 0

    def test_none_claim_is_a_no_op(self, user):
        sync_user_type(user, None, source="oidc")
        assert _group_names(user) == set()
        assert _role_sync_rows(user).count() == 0

    def test_never_grants_staff_or_superuser(self, user):
        sync_user_type(user, "ctf_organizer", source="oidc")
        user.refresh_from_db()
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_writes_one_audit_row_per_change(self, user):
        """The audit trail records each transition, the SEC-5 reviewability control."""
        sync_user_type(user, "ctf_participant", source="oidc")
        sync_user_type(user, "standard", source="dev_login")
        sync_user_type(user, "ctf_participant", source="identity_platform")
        # Order by insertion id, not timestamp: three rows can share a millisecond.
        sources = list(_role_sync_rows(user).order_by("id").values_list("context", flat=True))
        assert sources == [
            "user_type sync via oidc",
            "user_type sync via dev_login",
            "user_type sync via identity_platform",
        ]


@pytest.mark.django_db
class TestClaimDerivedGroupInvariant:
    """SEC-5: a self-assigned user_type can only ever reach CTF-scoped groups.

    Proves the safety invariant that makes self-mutable ``custom:user_type``
    acceptable: claim-derived groups never grant platform elevation
    (``is_staff`` / ``is_superuser``), the ``Threat Research`` group, or CMS
    authoring. Platform elevation stays env-email driven via
    ``apply_bootstrap_admin_flags``; this is a structural regression guard.
    """

    def test_mapping_reaches_only_participant_group(self):
        # #1516: self-service user_type may reach the CTF Participant group only.
        # Organizer is no longer derivable from self-service identity data; it is
        # granted from admin-controlled provider evidence or local assignment.
        reachable = {group for group in USER_TYPE_TO_GROUP.values() if group is not None}
        assert reachable == {CTF_PARTICIPANT_GROUP}

    def test_mapping_never_reaches_platform_or_organizer_groups(self):
        values = set(USER_TYPE_TO_GROUP.values())
        assert THREAT_RESEARCH_GROUP not in values
        assert CTF_ORGANIZER_GROUP not in values

    @pytest.mark.parametrize("claim", ["ctf_organizer", "ctf_participant"])
    def test_claim_derived_role_grants_no_cms_authoring(self, user, claim):
        sync_user_type(user, claim, source="oidc")
        user.refresh_from_db()
        # CMS authoring requires staff or Threat Research; CTF roles grant neither.
        assert can_edit_cms_authoring(user) is False
        assert THREAT_RESEARCH_GROUP not in set(user.groups.values_list("name", flat=True))
        assert user.is_staff is False
        assert user.is_superuser is False


@pytest.mark.django_db
class TestSelfServiceCannotAcquireOrganizer:
    """#1516: participant-controlled identity changes cannot acquire organizer,
    staff, superuser, or provisioning authority through the self-service sync,
    from any provider source. Re-verifies the #937 privilege-separation invariant
    against the narrowed mapping.
    """

    @pytest.mark.parametrize("source", ["oidc", "identity_platform", "dev_login"])
    def test_self_service_organizer_claim_grants_no_privilege(self, user, source):
        sync_user_type(user, "ctf_organizer", source=source)
        user.refresh_from_db()
        groups = _group_names(user)
        assert CTF_ORGANIZER_GROUP not in groups
        assert THREAT_RESEARCH_GROUP not in groups
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_toggling_user_type_never_reaches_organizer(self, user):
        # Any sequence of self-asserted user_type values a participant can drive
        # never lands them in the organizer group.
        for claim in ["ctf_participant", "ctf_organizer", "standard", "ctf_organizer"]:
            sync_user_type(user, claim, source="oidc")
        assert CTF_ORGANIZER_GROUP not in _group_names(user)
