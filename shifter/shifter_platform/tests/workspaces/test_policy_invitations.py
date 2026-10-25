"""Signed invitations add explicit principal facts, without application grants."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from management import services as identities
from shared.verified_identity import VerifiedIdentity
from tests.workspaces.test_account_policy_admin import Provider, _actor
from workspaces import services
from workspaces.models import Workspace, WorkspaceInvitation, WorkspaceMembership
from workspaces.services._invitations import _token

pytestmark = pytest.mark.django_db


def _workspace():
    account = services.create_account(kind="team", name="Team")
    return Workspace.objects.get(organization__account_id=account.id)


def test_service_issues_rotates_and_revokes_invitation_without_human_creator(monkeypatch):
    workspace = _workspace()
    actor = _actor("service", actions=frozenset({"workspace.manage_invitations"}))
    monkeypatch.setattr("workspaces.services._policy_invitations._schedule_delivery", lambda _: None)
    invitation = services.admin_issue_workspace_invitation(actor, Provider(), workspace.uuid, "recipient@example.test")
    row = WorkspaceInvitation.objects.get(public_id=invitation.invitation_uuid)
    assert row.created_by_id is None
    assert row.created_by_principal_uuid == actor.principal.uuid
    assert row.role == ""
    old_token = _token(row)
    services.admin_resend_workspace_invitation(actor, Provider(), workspace.uuid, row.public_id)
    with pytest.raises(services.WorkspaceInvitationError):
        services.stage_workspace_invitation_token(old_token)
    services.admin_revoke_workspace_invitation(actor, Provider(), workspace.uuid, row.public_id)
    row.refresh_from_db()
    assert row.revoked_at is not None
    assert not WorkspaceMembership.objects.filter(workspace=workspace).exists()


def test_acceptance_requires_fresh_matching_provider_binding_and_current_inviter_authority(monkeypatch):
    workspace = _workspace()
    actor = _actor("service", actions=frozenset({"workspace.manage_invitations"}))
    monkeypatch.setattr("workspaces.services._policy_invitations._schedule_delivery", lambda _: None)
    invitation = services.admin_issue_workspace_invitation(actor, Provider(), workspace.uuid, "recipient@example.test")
    row = WorkspaceInvitation.objects.get(public_id=invitation.invitation_uuid)
    claim = services.stage_workspace_invitation_token(_token(row))
    user = get_user_model().objects.create_user(username=f"recipient-{uuid4()}", email="recipient@example.test")
    principal = identities.principal_for_user(user)
    identities.bind_principal_provider_identity(principal, "https://identity.example.test", "subject-one")
    identity = VerifiedIdentity("https://identity.example.test", "subject-one", user.email, True)
    wrong = VerifiedIdentity(identity.issuer, "different-subject", user.email, True)
    for evidence, provider in ((wrong, Provider()), (identity, Provider(allowed=False))):
        with pytest.raises(services.WorkspaceInvitationError):
            services.policy_accept_workspace_invitation(user, evidence, claim, provider)
        assert not WorkspaceMembership.objects.filter(workspace=workspace, principal_uuid=principal.uuid).exists()
    services.policy_accept_workspace_invitation(user, identity, claim, Provider())
    membership = WorkspaceMembership.objects.get(workspace=workspace, principal_uuid=principal.uuid)
    assert membership.role == "" and membership.user_id is None
    row.refresh_from_db()
    assert row.accepted_by_principal_uuid == principal.uuid
    with pytest.raises(services.WorkspaceInvitationError):
        services.policy_accept_workspace_invitation(user, identity, claim, Provider())


def test_invitation_sibling_scope_cannot_be_managed(monkeypatch):
    first, sibling = _workspace(), _workspace()
    actor = _actor("service", actions=frozenset({"workspace.manage_invitations"}))
    monkeypatch.setattr("workspaces.services._policy_invitations._schedule_delivery", lambda _: None)
    invitation = services.admin_issue_workspace_invitation(actor, Provider(), first.uuid, "recipient@example.test")
    with pytest.raises(services.WorkspaceInvitationError):
        services.admin_revoke_workspace_invitation(actor, Provider(), sibling.uuid, invitation.invitation_uuid)
    assert WorkspaceInvitation.objects.get(public_id=invitation.invitation_uuid).revoked_at is None


def test_database_rejects_partial_principal_acceptance_and_mixed_creator(monkeypatch):
    from django.db import IntegrityError, transaction

    workspace = _workspace()
    actor = _actor("service", actions=frozenset({"workspace.manage_invitations"}))
    monkeypatch.setattr("workspaces.services._policy_invitations._schedule_delivery", lambda _: None)
    invitation = services.admin_issue_workspace_invitation(actor, Provider(), workspace.uuid, "recipient@example.test")
    for changes in ({"accepted_by_principal_uuid": actor.principal.uuid}, {"role": "owner"}):
        with pytest.raises(IntegrityError), transaction.atomic():
            WorkspaceInvitation.objects.filter(public_id=invitation.invitation_uuid).update(**changes)
