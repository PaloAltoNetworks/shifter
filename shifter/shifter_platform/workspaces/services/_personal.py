"""Personal-workspace provisioning: the #1325 compatibility default (ADR-046-R4).

Every user owns exactly one personal workspace inside its own personal
organization. That is what keeps a single-user install behaving identically
after the tenancy layer lands, without baking a deployment-global "Default"
organization into the schema -- a shared default would make every install
single-tenant by construction and would have to be unpicked before a university
or hosting operator could run more than one tenant.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction

from workspaces.models import (
    Organization,
    OrganizationMembership,
    Workspace,
    WorkspaceMembership,
)
from workspaces.roles import OrganizationRole, WorkspaceRole

from ._authorization import (
    WorkspaceAuthorization,
    WorkspaceAuthorizationError,
    _authorization_from,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

#: Personal organizations and workspaces are identified by their
#: ``personal_for_user`` link, never by a parsed display name, so the label
#: carries no username or email.
PERSONAL_NAME = "Personal"


def _persisted_owner_authorization(workspace: Workspace, user: User) -> WorkspaceAuthorization:
    """Return the persisted personal-owner grant or fail closed.

    A personal workspace without its owner's membership is malformed authority,
    not permission to synthesize or silently repair a grant during a request.
    """
    membership = (
        WorkspaceMembership.objects.select_related("workspace")
        .filter(
            workspace=workspace,
            user=user,
            role=WorkspaceRole.OWNER.value,
        )
        .first()
    )
    if membership is None:
        logger.warning(
            "resolve_personal_workspace: invalid persisted owner membership user_id=%s workspace_id=%s",
            user.pk,
            workspace.pk,
        )
        raise WorkspaceAuthorizationError("Workspace access denied")
    return _authorization_from(membership)


def resolve_personal_workspace(user: User) -> WorkspaceAuthorization:
    """Return ``user``'s personal workspace, creating it on first use.

    Idempotent and atomic: the organization, the workspace, and the owner
    membership are created together or not at all, so a failure part-way
    through never leaves a workspace without an owner. Concurrent first calls
    for the same user race on the unique ``personal_for_user`` column; the
    loser re-reads the winner's row.

    Returns:
        WorkspaceAuthorization: the owner-role authorization for the workspace.
    """
    existing = Workspace.objects.filter(personal_for_user=user).first()
    if existing is not None:
        return _persisted_owner_authorization(existing, user)

    try:
        with transaction.atomic():
            organization = Organization.objects.create(name=PERSONAL_NAME)
            workspace = Workspace.objects.create(
                organization=organization,
                name=PERSONAL_NAME,
                personal_for_user=user,
            )
            membership = WorkspaceMembership.objects.create(
                workspace=workspace,
                user=user,
                role=WorkspaceRole.OWNER.value,
            )
            # The personal organization's bootstrap admin is its owner (ADR-048).
            # Persisted here so organization authority is read from the membership
            # row, never re-inferred from the workspace role at authorization time.
            OrganizationMembership.objects.create(
                organization=organization,
                user=user,
                role=OrganizationRole.ADMIN.value,
            )
    except Exception:
        # A concurrent caller may have won the unique personal_for_user race.
        concurrent = Workspace.objects.filter(personal_for_user=user).first()
        if concurrent is None:
            raise
        logger.debug("resolve_personal_workspace: reusing concurrently created workspace user_id=%s", user.pk)
        return _persisted_owner_authorization(concurrent, user)

    logger.info("resolve_personal_workspace: created personal workspace user_id=%s", user.pk)
    return _authorization_from(membership)
