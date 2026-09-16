"""Workspace member invitation persistence (#1942, PLAT-235)."""

import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from workspaces.roles import WorkspaceRole


class WorkspaceInvitation(models.Model):
    """One revocable, expiring pre-membership grant for a workspace address."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField(max_length=254)
    role = models.CharField(max_length=32, choices=WorkspaceRole.choices)
    generation = models.UUIDField(default=uuid.uuid4, editable=False)
    expires_at = models.DateTimeField(db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="workspace_invitations_created",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_invitations_accepted",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Database-level invitation lifecycle invariants."""

        db_table = "workspaces_workspaceinvitation"
        ordering = ["workspace_id", "-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                "workspace",
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="uniq_current_invitation_workspace_email_ci",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=WorkspaceRole.values),
                name="workspace_invitation_role_valid",
            ),
            models.CheckConstraint(
                condition=~(models.Q(accepted_at__isnull=False) & models.Q(revoked_at__isnull=False)),
                name="workspace_invitation_one_terminal_state",
            ),
            models.CheckConstraint(
                condition=models.Q(accepted_by__isnull=True) | models.Q(accepted_at__isnull=False),
                name="workspace_invitation_acceptance_complete",
            ),
        ]

    def __str__(self) -> str:
        """Return a bounded diagnostic representation without recipient PII."""
        return f"invitation:{self.public_id}@workspace:{self.workspace_id}"
