"""Behavior tests for administrator-controlled CTF Organizer authorization.

``config/organizer_authority.py`` is the single seam that grants the
``CTF Organizer`` group from an administrator-controlled source (verified
provider group evidence or explicit local assignment). Issue #1516 requires that
self-service identity data can never reach this group; these tests prove the
provider mapping is allowlisted, fail-closed, additive, audited, and never grants
staff / superuser / Threat Research.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings

from config.organizer_authority import (
    ORGANIZER_SOURCE_LOCAL,
    ORGANIZER_SOURCE_PROVIDER,
    grant_local_organizer,
    provider_group_organizer_allowlist,
    reconcile_provider_privileged_groups,
)
from management.services import get_user_profile
from shared.audit import (
    AuditAction,
    AuditActorType,
    AuditEntityType,
)
from shared.auth import CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP, THREAT_RESEARCH_GROUP
from shared.models import AuditLog

User = get_user_model()

ALLOWLISTED = "shifter-ctf-organizers"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="u@example.com", email="u@example.com")


def _group_names(user) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def _organizer_source(user) -> str:
    return get_user_profile(user).organizer_grant_source


def _role_sync_rows(user):
    return AuditLog.objects.filter(
        entity_type=AuditEntityType.USER,
        entity_id=user.id,
        action=AuditAction.ROLE_SYNC,
    )


@pytest.mark.django_db
class TestProviderGroupMapping:
    @pytest.fixture(autouse=True)
    def _allowlist(self, settings):
        # Class-level override_settings only works on Django TestCase subclasses;
        # the pytest-django settings fixture is the plain-class equivalent and
        # auto-reverts after each test.
        settings.CTF_ORGANIZER_PROVIDER_GROUPS = [ALLOWLISTED]

    def test_allowlisted_provider_group_grants_organizer_and_audits(self, user):
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        assert _group_names(user) == {CTF_ORGANIZER_GROUP}
        assert _organizer_source(user) == ORGANIZER_SOURCE_PROVIDER
        row = _role_sync_rows(user).get()
        assert CTF_ORGANIZER_GROUP in row.new_state["groups"]
        # System-attributed: it was administrator-controlled provider evidence,
        # not a self-service action by the subject user.
        assert row.actor_type == AuditActorType.SYSTEM

    def test_non_allowlisted_provider_group_grants_nothing(self, user):
        reconcile_provider_privileged_groups(user, {"cognito:groups": ["some-other-group"]})
        assert _group_names(user) == set()
        assert _role_sync_rows(user).count() == 0

    def test_grant_is_idempotent_no_duplicate_audit(self, user):
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        assert _role_sync_rows(user).count() == 1

    @pytest.mark.parametrize(
        "claim",
        [{}, {"cognito:groups": None}, {"cognito:groups": "not-a-list"}, {"cognito:groups": 123}],
        ids=["absent", "none", "string", "int"],
    )
    def test_garbage_or_absent_claim_grants_nothing(self, user, claim):
        reconcile_provider_privileged_groups(user, claim)
        assert _group_names(user) == set()

    def test_never_grants_staff_superuser_or_threat_research(self, user):
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        user.refresh_from_db()
        assert user.is_staff is False
        assert user.is_superuser is False
        assert THREAT_RESEARCH_GROUP not in _group_names(user)


@pytest.mark.django_db
class TestFailClosed:
    @override_settings(CTF_ORGANIZER_PROVIDER_GROUPS=[])
    def test_empty_allowlist_grants_nothing(self, user):
        # Even a provider group named exactly like a real one grants nothing when
        # the allowlist is unset — the provider path is fail-closed.
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        assert _group_names(user) == set()

    @override_settings(CTF_ORGANIZER_PROVIDER_GROUPS=[])
    def test_allowlist_helper_empty_when_unset(self):
        assert provider_group_organizer_allowlist() == frozenset()

    @override_settings(CTF_ORGANIZER_PROVIDER_GROUPS=[ALLOWLISTED, "  ", ""])
    def test_allowlist_helper_strips_blanks(self):
        assert provider_group_organizer_allowlist() == frozenset({ALLOWLISTED})


@pytest.mark.django_db
class TestLocalAssignment:
    def test_grant_local_organizer_adds_group_and_audits(self, user):
        grant_local_organizer(user, source="dev_login")
        assert CTF_ORGANIZER_GROUP in _group_names(user)
        assert _organizer_source(user) == ORGANIZER_SOURCE_LOCAL
        assert _role_sync_rows(user).count() == 1

    def test_local_grant_preserves_existing_participant_group(self, user):
        user.groups.add(Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)[0])
        grant_local_organizer(user, source="dev_login")
        assert _group_names(user) == {CTF_ORGANIZER_GROUP, CTF_PARTICIPANT_GROUP}


@pytest.mark.django_db
class TestProviderRevocation:
    """The provider group is authoritative: when the admin removes a user from
    the allowlisted provider group, the next verified login revokes the
    provider-derived organizer membership. Explicit local assignments and
    unknown-provenance memberships are never auto-revoked.
    """

    @pytest.fixture(autouse=True)
    def _allowlist(self, settings):
        settings.CTF_ORGANIZER_PROVIDER_GROUPS = [ALLOWLISTED]

    def test_provider_derived_organizer_revoked_when_evidence_absent(self, user):
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        assert _organizer_source(user) == ORGANIZER_SOURCE_PROVIDER
        # A later verified login with the group removed revokes the membership.
        reconcile_provider_privileged_groups(user, {"cognito:groups": []})
        assert CTF_ORGANIZER_GROUP not in _group_names(user)
        assert _organizer_source(user) == ""
        # Grant + revoke both audited.
        assert _role_sync_rows(user).count() == 2

    def test_local_organizer_not_revoked_by_absent_provider_evidence(self, user):
        grant_local_organizer(user, source="dev_login")
        reconcile_provider_privileged_groups(user, {"cognito:groups": ["unrelated"]})
        assert CTF_ORGANIZER_GROUP in _group_names(user)
        assert _organizer_source(user) == ORGANIZER_SOURCE_LOCAL

    def test_admin_added_local_organizer_not_revoked(self, user):
        # A membership added directly (e.g. superuser via Django admin) is recorded
        # as local provenance by the m2m signal and must not be auto-revoked.
        user.groups.add(Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0])
        assert _organizer_source(user) == ORGANIZER_SOURCE_LOCAL
        reconcile_provider_privileged_groups(user, {"cognito:groups": []})
        assert CTF_ORGANIZER_GROUP in _group_names(user)


@pytest.mark.django_db
class TestDjangoAdminMembershipSignal:
    """Out-of-band CTF Organizer changes (e.g. the Django admin editing groups)
    are coupled to provenance and a ROLE_SYNC audit row by the m2m_changed signal
    (issue #1516, codex cycle 2). Explicit local assignments are then never
    auto-revoked, and admin remove+re-add clears stale provider provenance.
    """

    def test_direct_add_records_local_provenance_and_audits(self, user):
        user.groups.add(Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0])
        assert _organizer_source(user) == ORGANIZER_SOURCE_LOCAL
        assert _role_sync_rows(user).count() == 1

    def test_direct_remove_clears_provenance_and_audits(self, user):
        org = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0]
        user.groups.add(org)
        user.groups.remove(org)
        assert CTF_ORGANIZER_GROUP not in _group_names(user)
        assert _organizer_source(user) == ""
        assert _role_sync_rows(user).count() == 2

    def test_admin_readd_of_provider_org_becomes_local_and_survives_revocation(self, settings, user):
        settings.CTF_ORGANIZER_PROVIDER_GROUPS = [ALLOWLISTED]
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        assert _organizer_source(user) == ORGANIZER_SOURCE_PROVIDER
        org = Group.objects.get(name=CTF_ORGANIZER_GROUP)
        # Admin removes then re-adds via the group m2m (Django admin User form).
        user.groups.remove(org)
        assert _organizer_source(user) == ""
        user.groups.add(org)
        assert _organizer_source(user) == ORGANIZER_SOURCE_LOCAL
        # No longer provider-derived, so a later provider login without the group
        # does not revoke it (this closes the stale-provenance finding).
        reconcile_provider_privileged_groups(user, {"cognito:groups": []})
        assert CTF_ORGANIZER_GROUP in _group_names(user)

    def test_non_organizer_group_change_is_ignored(self, user):
        user.groups.add(Group.objects.get_or_create(name=CTF_PARTICIPANT_GROUP)[0])
        assert _organizer_source(user) == ""
        assert _role_sync_rows(user).count() == 0

    def test_reverse_direction_group_membership_edit_is_reconciled(self, user):
        # The Django admin Group change form edits membership via the reverse
        # accessor (group.user_set), which fires m2m_changed with reverse=True.
        # The signal must reconcile provenance + audit identically to the forward
        # (User form) path.
        org = Group.objects.get_or_create(name=CTF_ORGANIZER_GROUP)[0]
        org.user_set.add(user)
        assert _organizer_source(user) == ORGANIZER_SOURCE_LOCAL
        assert _role_sync_rows(user).count() == 1
        org.user_set.remove(user)
        assert CTF_ORGANIZER_GROUP not in _group_names(user)
        assert _organizer_source(user) == ""
        assert _role_sync_rows(user).count() == 2


@pytest.mark.django_db
class TestEmptyAllowlistNeverRevokes:
    def test_absent_config_does_not_revoke_provider_organizer(self, user, settings):
        # Grant while configured, then a login with the allowlist unset must NOT
        # strip authority — a missing configuration disables the path, it does not
        # revoke everyone.
        settings.CTF_ORGANIZER_PROVIDER_GROUPS = [ALLOWLISTED]
        reconcile_provider_privileged_groups(user, {"cognito:groups": [ALLOWLISTED]})
        assert CTF_ORGANIZER_GROUP in _group_names(user)
        settings.CTF_ORGANIZER_PROVIDER_GROUPS = []
        reconcile_provider_privileged_groups(user, {"cognito:groups": []})
        assert CTF_ORGANIZER_GROUP in _group_names(user)
        assert _organizer_source(user) == ORGANIZER_SOURCE_PROVIDER
