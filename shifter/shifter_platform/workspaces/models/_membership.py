"""WorkspaceMembership model - a user's role in a workspace (ADR-046)."""

from django.conf import settings
from django.db import models

from workspaces.roles import WorkspaceRole


class WorkspaceMembership(models.Model):
    """One user's role in one workspace.

    Uniqueness on ``(workspace, user)`` is the database-level proof that a user
    holds a single role per workspace. The role vocabulary is closed
    (:class:`~workspaces.roles.WorkspaceRole`) and protected by a database
    check constraint.

    A membership is *workspace-level authorization only*. It is not a grant to
    use another member's range: per-range SSH, RDP, VPN, Guacamole, CTF
    participant/event, and lifecycle checks keep their existing owner semantics
    and remain mandatory (ADR-046-R2).
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=32,
        choices=WorkspaceRole.choices,
        help_text="Closed role code; the role-to-operation policy lives in workspaces.roles.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        db_table = "workspaces_workspacemembership"
        ordering = ["workspace_id", "user_id"]
        verbose_name = "Workspace membership"
        verbose_name_plural = "Workspace memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="uniq_membership_per_workspace_user",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=WorkspaceRole.values),
                name="workspace_membership_role_valid",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.role}@{self.workspace_id}:{self.user_id}"
