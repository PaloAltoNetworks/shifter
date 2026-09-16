"""PostgreSQL proofs for invitation issuance and acceptance serialization."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from shared.audit import AuditActorType
from shared.verified_identity import VerifiedIdentity
from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceInvitation, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
User = get_user_model()


def _accept(invitation_uuid, generation, user_id, barrier):
    barrier.wait(timeout=10)
    user = User.objects.get(pk=user_id)
    claim = services.WorkspaceInvitationClaim(invitation_uuid=invitation_uuid, generation=generation)
    identity = VerifiedIdentity(
        issuer="https://issuer.example.test",
        subject=f"concurrent-{user_id}",
        email=user.email,
        email_verified=True,
        source="test",
    )
    try:
        result = services.accept_workspace_invitation(
            user,
            identity,
            claim,
            audit=services.MembershipAuditContext(actor_type=AuditActorType.USER, actor_id=user.pk),
        )
    except services.WorkspaceInvitationError as exc:
        return ("error", exc.code)
    finally:
        connection.close()
    return ("ok", result.membership_id)


def test_concurrent_acceptance_creates_exactly_one_membership():
    owner = User.objects.create_user(username="race-owner@example.com", email="race-owner@example.com")
    invitee = User.objects.create_user(username="race-invitee@example.com", email="race-invitee@example.com")
    workspace = Workspace.objects.create(
        organization=Organization.objects.create(name="Race Lab"),
        name="Race Workspace",
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER)
    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=invitee.email,
        role=WorkspaceRole.MEMBER,
        expires_at=timezone.now() + timedelta(hours=1),
        created_by=owner,
    )
    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda _: _accept(invitation.public_id, invitation.generation, invitee.pk, barrier),
                range(2),
            )
        )

    assert sorted(result[0] for result in outcomes) == ["error", "ok"]
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=invitee).count() == 1
    invitation.refresh_from_db()
    assert invitation.accepted_by_id == invitee.pk
    assert invitation.accepted_at is not None
