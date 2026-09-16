"""Workspace member invitation lifecycle tests (#1942, PLAT-235)."""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import unquote

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone

from shared.audit import AuditAction, AuditActorType, AuditEntityType
from shared.models import AuditLog
from shared.verified_identity import VerifiedIdentity
from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceInvitation, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
_TOKEN_RE = re.compile(r"#token=([^\s<\"']+)")


def _user(suffix: str, *, email: str | None = None, staff: bool = False):
    address = email or f"invite-{suffix}@example.com"
    return User.objects.create_user(username=address, email=address, is_staff=staff)


def _shared_workspace():
    owner = _user("owner", staff=True)
    workspace = Workspace.objects.create(
        organization=Organization.objects.create(name="Invitation Lab"),
        name="Shared",
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER)
    return owner, workspace


def _audit(actor) -> services.MembershipAuditContext:
    return services.MembershipAuditContext(
        actor_type=AuditActorType.USER,
        actor_id=actor.pk,
        source_ip="192.0.2.44",
        user_agent="invitation-test",
        request_id="invitation-request",
    )


def _verified(user, *, email: str | None = None) -> VerifiedIdentity:
    return VerifiedIdentity(
        issuer="https://issuer.example.test",
        subject=f"subject-{user.pk}",
        email=email or user.email,
        email_verified=True,
        source="test",
    )


def _issue(owner, workspace, email: str, recorded_workspace_email, role: str = WorkspaceRole.MEMBER):
    projection = services.issue_workspace_invitation(
        owner,
        workspace.uuid,
        email,
        role,
        audit=_audit(owner),
    )
    message = recorded_workspace_email.get(timeout=2)
    html = message.alternatives[0][0]
    text = message.body
    html_token = _TOKEN_RE.search(html)
    text_token = _TOKEN_RE.search(text)
    assert html_token is not None
    assert text_token is not None
    assert html_token.group(1) == text_token.group(1)
    return projection, unquote(html_token.group(1))


def test_issue_uses_django_timestamp_signing_and_post_commit_email(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()

    projection, token = _issue(
        owner, workspace, " New.Person@Example.COM ", recorded_workspace_email, WorkspaceRole.ADMIN
    )

    payload = signing.loads(token, salt=services.WORKSPACE_INVITATION_SIGNING_SALT, max_age=3600)
    invitation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid)
    assert payload == {
        "v": 1,
        "invitation": str(invitation.public_id),
        "generation": str(invitation.generation),
    }
    assert projection.email == "new.person@example.com"
    assert projection.role == WorkspaceRole.ADMIN
    assert projection.status == "pending"
    assert AuditLog.objects.filter(
        entity_type=AuditEntityType.WORKSPACE_INVITATION,
        entity_id=invitation.pk,
        action=AuditAction.CREATE,
    ).exists()


@pytest.mark.parametrize(
    "site_url",
    [
        "http://shifter.example.test",
        "https://user:password@shifter.example.test",
        "https://shifter.example.test/unexpected-path",
    ],
)
def test_issue_rejects_unsafe_delivery_origins(settings, site_url):
    settings.DEBUG = False
    settings.SITE_URL = site_url
    owner, workspace = _shared_workspace()
    audit = _audit(owner)

    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.issue_workspace_invitation(
            owner,
            workspace.uuid,
            "safe-origin@example.com",
            WorkspaceRole.MEMBER,
            audit=audit,
        )

    assert caught.value.code == "invitation_delivery_unavailable"
    assert not WorkspaceInvitation.objects.filter(workspace=workspace).exists()


@pytest.mark.parametrize("token", ["not-signed", "", "x" * 4097])
def test_stage_rejects_malformed_or_oversize_tokens(token):
    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.stage_workspace_invitation_token(token)
    assert caught.value.code == "invitation_invalid"


def test_tampered_expired_revoked_and_consumed_tokens_share_bounded_failure(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    invitee = _user("invitee")
    projection, token = _issue(owner, workspace, invitee.email, recorded_workspace_email)

    for bad_token in (f"{token}x",):
        with pytest.raises(services.WorkspaceInvitationError) as caught:
            services.stage_workspace_invitation_token(bad_token)
        assert caught.value.code == "invitation_invalid"

    invitation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid)
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    invitation.save(update_fields=["expires_at"])
    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.stage_workspace_invitation_token(token)
    assert caught.value.code == "invitation_invalid"

    invitation.expires_at = timezone.now() + timedelta(days=1)
    invitation.save(update_fields=["expires_at"])
    services.revoke_workspace_invitation(owner, workspace.uuid, invitation.public_id, audit=_audit(owner))
    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.stage_workspace_invitation_token(token)
    assert caught.value.code == "invitation_invalid"


def test_resend_rotates_generation_and_invalidates_the_old_token(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    projection, first_token = _issue(owner, workspace, "rotate@example.com", recorded_workspace_email)
    first_generation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid).generation

    resent = services.resend_workspace_invitation(
        owner,
        workspace.uuid,
        projection.invitation_uuid,
        audit=_audit(owner),
    )
    second_message = recorded_workspace_email.get(timeout=2)
    second_token = unquote(_TOKEN_RE.search(second_message.body).group(1))
    invitation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid)

    assert resent.status == "pending"
    assert invitation.generation != first_generation
    with pytest.raises(services.WorkspaceInvitationError):
        services.stage_workspace_invitation_token(first_token)
    assert services.stage_workspace_invitation_token(second_token).generation == invitation.generation


def test_accept_requires_fresh_matching_verified_identity_and_creates_exactly_one_membership(
    settings, recorded_workspace_email
):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    invitee = _user("accept", email="Accept.Me@Example.com")
    projection, token = _issue(owner, workspace, "accept.me@example.COM", recorded_workspace_email, WorkspaceRole.ADMIN)
    claim = services.stage_workspace_invitation_token(token)
    mismatched_identity = _verified(invitee, email="different@example.com")
    invitee_audit = _audit(invitee)

    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.accept_workspace_invitation(
            invitee,
            mismatched_identity,
            claim,
            audit=invitee_audit,
        )
    assert caught.value.code == "invitation_invalid"

    membership = services.accept_workspace_invitation(
        invitee,
        _verified(invitee, email="ACCEPT.ME@example.com"),
        claim,
        audit=_audit(invitee),
    )

    assert membership.user_id == invitee.pk
    assert membership.role == WorkspaceRole.ADMIN
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=invitee).count() == 1
    invitation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid)
    assert invitation.accepted_by_id == invitee.pk
    assert invitation.accepted_at is not None
    assert invitation.revoked_at is None

    verified_identity = _verified(invitee)
    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.accept_workspace_invitation(invitee, verified_identity, claim, audit=invitee_audit)
    assert caught.value.code == "invitation_invalid"
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=invitee).count() == 1


def test_accepted_invitation_history_survives_account_deletion(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    invitee = _user("deleted-after-accept")
    projection, token = _issue(owner, workspace, invitee.email, recorded_workspace_email)
    services.accept_workspace_invitation(
        invitee,
        _verified(invitee),
        services.stage_workspace_invitation_token(token),
        audit=_audit(invitee),
    )

    invitee.delete()

    invitation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid)
    assert invitation.accepted_at is not None
    assert invitation.accepted_by is None


def test_accept_fails_closed_for_ambiguous_active_accounts(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    invitee = _user("ambiguous-1", email="ambiguous@example.com")
    _user("ambiguous-2", email="AMBIGUOUS@example.com")
    _projection, token = _issue(owner, workspace, "ambiguous@example.com", recorded_workspace_email)
    identity = _verified(invitee)
    claim = services.stage_workspace_invitation_token(token)
    audit = _audit(invitee)

    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.accept_workspace_invitation(
            invitee,
            identity,
            claim,
            audit=audit,
        )

    assert caught.value.code == "invitation_invalid"
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=invitee).exists()


def test_existing_membership_is_never_silently_changed_by_acceptance(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    invitee = _user("existing")
    _projection, token = _issue(owner, workspace, invitee.email, recorded_workspace_email, WorkspaceRole.ADMIN)
    WorkspaceMembership.objects.create(workspace=workspace, user=invitee, role=WorkspaceRole.MEMBER)
    identity = _verified(invitee)
    claim = services.stage_workspace_invitation_token(token)
    audit = _audit(invitee)

    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.accept_workspace_invitation(
            invitee,
            identity,
            claim,
            audit=audit,
        )

    assert caught.value.code == "membership_exists"
    assert WorkspaceMembership.objects.get(workspace=workspace, user=invitee).role == WorkspaceRole.MEMBER


def test_admin_cannot_manage_owner_invitation_and_member_cannot_manage_any_invitation(
    settings, recorded_workspace_email
):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    admin = _user("admin")
    member = _user("member")
    WorkspaceMembership.objects.create(workspace=workspace, user=admin, role=WorkspaceRole.ADMIN)
    WorkspaceMembership.objects.create(workspace=workspace, user=member, role=WorkspaceRole.MEMBER)
    admin_audit = _audit(admin)
    member_audit = _audit(member)

    with pytest.raises(services.WorkspaceMembershipError) as caught:
        services.issue_workspace_invitation(
            admin,
            workspace.uuid,
            "future-owner@example.com",
            WorkspaceRole.OWNER,
            audit=admin_audit,
        )
    assert caught.value.code == "owner_authority_required"

    with pytest.raises(services.WorkspaceAuthorizationError):
        services.issue_workspace_invitation(
            member,
            workspace.uuid,
            "future-member@example.com",
            WorkspaceRole.MEMBER,
            audit=member_audit,
        )

    projection, _token = _issue(
        owner, workspace, "owner-invite@example.com", recorded_workspace_email, WorkspaceRole.OWNER
    )
    with pytest.raises(services.WorkspaceMembershipError) as caught:
        services.revoke_workspace_invitation(
            admin,
            workspace.uuid,
            projection.invitation_uuid,
            audit=admin_audit,
        )
    assert caught.value.code == "owner_authority_required"


def test_personal_and_archived_workspaces_reject_invitation_mutation(settings):
    settings.SITE_URL = "https://shifter.example.test"
    personal_owner = _user("personal", staff=True)
    personal = services.resolve_personal_workspace(personal_owner)
    personal_audit = _audit(personal_owner)

    with pytest.raises(services.WorkspaceMembershipError) as caught:
        services.issue_workspace_invitation(
            personal_owner,
            personal.workspace_uuid,
            "collaborator@example.com",
            WorkspaceRole.MEMBER,
            audit=personal_audit,
        )
    assert caught.value.code == "personal_workspace_protected"

    owner, workspace = _shared_workspace()
    workspace.archived_at = timezone.now()
    workspace.save(update_fields=["archived_at"])
    owner_audit = _audit(owner)
    with pytest.raises(services.WorkspaceInvitationError) as caught:
        services.issue_workspace_invitation(
            owner,
            workspace.uuid,
            "archived@example.com",
            WorkspaceRole.MEMBER,
            audit=owner_audit,
        )
    assert caught.value.code == "workspace_archived"


def test_expired_status_is_derived_without_mutating_the_row(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    projection, _token = _issue(owner, workspace, "expired@example.com", recorded_workspace_email)
    invitation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid)
    invitation.expires_at = timezone.now() - timedelta(seconds=1)
    invitation.save(update_fields=["expires_at"])

    listed = services.list_workspace_invitations(owner, workspace.uuid)

    assert listed[0].status == "expired"
    invitation.refresh_from_db()
    assert invitation.accepted_at is None
    assert invitation.revoked_at is None


def test_acceptance_audits_invitation_and_canonical_membership_create(settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner, workspace = _shared_workspace()
    invitee = _user("audit")
    projection, token = _issue(owner, workspace, invitee.email, recorded_workspace_email)

    membership = services.accept_workspace_invitation(
        invitee,
        _verified(invitee),
        services.stage_workspace_invitation_token(token),
        audit=_audit(invitee),
    )

    invitation = WorkspaceInvitation.objects.get(public_id=projection.invitation_uuid)
    assert AuditLog.objects.filter(
        entity_type=AuditEntityType.WORKSPACE_INVITATION,
        entity_id=invitation.pk,
        action=AuditAction.CLOSE,
    ).exists()
    assert AuditLog.objects.filter(
        entity_type=AuditEntityType.WORKSPACE_MEMBERSHIP,
        entity_id=membership.membership_id,
        action=AuditAction.CREATE,
    ).exists()
    serialized = " ".join(
        str(value)
        for row in AuditLog.objects.filter(entity_id__in=[invitation.pk, membership.membership_id])
        for value in (row.previous_state, row.new_state, row.context)
    )
    assert invitee.email not in serialized
    assert token not in serialized
