"""Behavior tests for the organization profile service and authority (ADR-048).

Drives the real organization read/update service through its authority boundary:
an ``admin`` organization membership or a Django superuser may act; anyone else
gets one opaque denial; updates are atomic, write only changed fields, and emit
one strict audit event that records field *names* only.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model

from shared.audit import AuditAction, AuditActorType, AuditEntityType
from shared.models import AuditLog
from workspaces import services
from workspaces.models import Organization, OrganizationMembership
from workspaces.roles import OrganizationRole

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix: str, *, is_superuser: bool = False):
    return User.objects.create_user(
        username=f"org-{suffix}@example.com",
        email=f"org-{suffix}@example.com",
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )


def _organization(name: str = "Research Lab", **fields) -> Organization:
    return Organization.objects.create(name=name, **fields)


def _admin_of(organization: Organization, suffix: str = "admin"):
    actor = _user(suffix)
    OrganizationMembership.objects.create(organization=organization, user=actor, role=OrganizationRole.ADMIN)
    return actor


def _audit(actor) -> services.OrganizationAuditContext:
    return services.OrganizationAuditContext(
        actor_type=AuditActorType.USER,
        actor_id=actor.pk,
        source_ip="192.0.2.10",
        user_agent="org-test",
        request_id="org-request",
    )


# ---------------------------------------------------------------------------
# Read authority
# ---------------------------------------------------------------------------


def test_admin_reads_the_organization_profile():
    organization = _organization(description="desc", support_email="h@e.com", support_url="https://e.com")
    admin = _admin_of(organization)

    profile = services.get_organization_profile(admin, organization.uuid)

    assert profile.uuid == organization.uuid
    assert profile.name == "Research Lab"
    assert profile.description == "desc"
    assert profile.support_email == "h@e.com"
    assert profile.support_url == "https://e.com"


def test_superuser_reads_any_organization_without_a_membership():
    organization = _organization()
    superuser = _user("root", is_superuser=True)

    profile = services.get_organization_profile(superuser, organization.uuid)

    assert profile.uuid == organization.uuid


def test_non_member_read_is_denied_opaquely():
    organization = _organization()
    outsider = _user("outsider")

    with pytest.raises(services.OrganizationAuthorizationError):
        services.get_organization_profile(outsider, organization.uuid)


def test_staff_without_membership_or_superuser_is_denied():
    organization = _organization()
    staff = User.objects.create_user(username="s@e.com", email="s@e.com", is_staff=True)

    with pytest.raises(services.OrganizationAuthorizationError):
        services.get_organization_profile(staff, organization.uuid)


def test_missing_organization_and_unauthorized_share_one_message():
    organization = _organization()
    outsider = _user("outsider")

    with pytest.raises(services.OrganizationAuthorizationError) as missing:
        services.get_organization_profile(outsider, uuid.uuid4())
    with pytest.raises(services.OrganizationAuthorizationError) as forbidden:
        services.get_organization_profile(outsider, organization.uuid)

    assert str(missing.value) == str(forbidden.value)


def test_malformed_uuid_is_denied_not_a_value_error():
    outsider = _user("outsider")

    with pytest.raises(services.OrganizationAuthorizationError):
        services.get_organization_profile(outsider, "not-a-uuid")


# ---------------------------------------------------------------------------
# Update authority and semantics
# ---------------------------------------------------------------------------


def test_admin_updates_only_supplied_fields():
    organization = _organization(description="old", support_email="old@e.com")
    admin = _admin_of(organization)

    profile = services.update_organization_profile(
        admin, organization.uuid, {"description": "new"}, audit=_audit(admin)
    )

    assert profile.description == "new"
    # An absent field is unchanged (PATCH mask), not blanked.
    assert profile.support_email == "old@e.com"
    organization.refresh_from_db()
    assert organization.description == "new"
    assert organization.support_email == "old@e.com"


def test_empty_string_clears_a_field():
    organization = _organization(support_url="https://e.com")
    admin = _admin_of(organization)

    profile = services.update_organization_profile(admin, organization.uuid, {"support_url": ""}, audit=_audit(admin))

    assert profile.support_url == ""


def test_update_writes_one_strict_audit_event_with_field_names_only():
    organization = _organization()
    admin = _admin_of(organization)
    before = AuditLog.objects.count()

    services.update_organization_profile(
        admin,
        organization.uuid,
        {"description": "secret detail", "support_email": "h@e.com"},
        audit=_audit(admin),
    )

    assert AuditLog.objects.count() == before + 1
    event = AuditLog.objects.latest("id")
    assert event.entity_type == AuditEntityType.ORGANIZATION
    assert event.entity_id == organization.pk
    assert event.action == AuditAction.UPDATE
    assert sorted(event.new_state["changed_fields"]) == ["description", "support_email"]
    assert event.new_state["organization_id"] == organization.pk
    assert event.new_state["superuser_override"] is False
    # The audit record must never copy the field values themselves.
    serialized = str(event.new_state)
    assert "secret detail" not in serialized
    assert "h@e.com" not in serialized


def test_no_op_update_writes_nothing_and_records_no_audit():
    organization = _organization(description="same")
    admin = _admin_of(organization)
    before = AuditLog.objects.count()

    profile = services.update_organization_profile(
        admin, organization.uuid, {"description": "same"}, audit=_audit(admin)
    )

    assert profile.description == "same"
    assert AuditLog.objects.count() == before


def test_empty_change_set_is_a_no_op():
    organization = _organization()
    admin = _admin_of(organization)
    before = AuditLog.objects.count()

    services.update_organization_profile(admin, organization.uuid, {}, audit=_audit(admin))

    assert AuditLog.objects.count() == before


def test_superuser_update_is_recorded_as_an_override():
    organization = _organization()
    superuser = _user("root", is_superuser=True)

    services.update_organization_profile(
        superuser, organization.uuid, {"description": "by-operator"}, audit=_audit(superuser)
    )

    event = AuditLog.objects.latest("id")
    assert event.new_state["superuser_override"] is True
    organization.refresh_from_db()
    assert organization.description == "by-operator"


def test_non_admin_update_is_denied_and_persists_nothing():
    organization = _organization(description="original")
    outsider = _user("outsider")
    audit = _audit(outsider)
    before = AuditLog.objects.count()

    with pytest.raises(services.OrganizationAuthorizationError):
        services.update_organization_profile(outsider, organization.uuid, {"description": "hacked"}, audit=audit)

    organization.refresh_from_db()
    assert organization.description == "original"
    assert AuditLog.objects.count() == before


# ---------------------------------------------------------------------------
# Service-owned domain validation (ADR-046-R12, ADR-048-R6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"support_email": "not-an-email"}, id="bad-email"),
        pytest.param({"support_url": "not a url"}, id="bad-url"),
        pytest.param({"name": ""}, id="blank-name"),
        pytest.param({"name": "   "}, id="whitespace-name"),
        pytest.param({"description": "x" * 2001}, id="over-length-description"),
        pytest.param({"unknown_field": "x"}, id="unknown-field"),
    ],
)
def test_update_validates_field_invariants_for_every_caller(changes):
    organization = _organization(description="original")
    admin = _admin_of(organization)
    audit = _audit(admin)
    before = AuditLog.objects.count()

    with pytest.raises(services.OrganizationValidationError):
        services.update_organization_profile(admin, organization.uuid, changes, audit=audit)

    organization.refresh_from_db()
    assert organization.description == "original"
    assert AuditLog.objects.count() == before


# ---------------------------------------------------------------------------
# Administrable-organization discovery (ADR-048 authority, not workspace context)
# ---------------------------------------------------------------------------


def test_admin_lists_only_organizations_it_administers():
    administered = _organization("Administered")
    admin = _admin_of(administered)
    _organization("Other")  # admin holds no membership here

    result = services.list_administrable_organizations(admin)

    assert [profile.uuid for profile in result] == [administered.uuid]


def test_superuser_lists_every_organization():
    first = _organization("Alpha")
    second = _organization("Beta")
    superuser = _user("root", is_superuser=True)

    result = services.list_administrable_organizations(superuser)

    assert {profile.uuid for profile in result} == {first.uuid, second.uuid}


def test_non_admin_lists_no_organizations():
    _organization("Some Org")
    outsider = _user("outsider")

    assert services.list_administrable_organizations(outsider) == []
