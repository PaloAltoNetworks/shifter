"""Explicit workspace ownership facts, independently of membership and policy."""

from django.db import models


class WorkspaceOwnership(models.Model):
    """Several owners may exist; services preserve the incumbent last-owner rule."""

    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="ownerships")
    principal_uuid = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """One ownership fact per workspace and durable principal."""

        db_table = "workspaces_workspaceownership"
        constraints = [
            models.UniqueConstraint(fields=["workspace", "principal_uuid"], name="uniq_workspace_principal_owner")
        ]

    def __str__(self) -> str:
        """Return a bounded ownership identity."""
        return f"workspace-owner:{self.workspace_id}:{self.principal_uuid}"
