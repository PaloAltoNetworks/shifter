"""Dormant workspace admin inspection; all authoring uses policy service commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.core.exceptions import PermissionDenied

from shared.admin_policy import PolicyReadOnlyAdmin
from shared.authorization import configured_authorization_provider
from workspaces.models import WorkspaceInvitation, WorkspaceQuotaPolicy
from workspaces.services._account_policy_admin import _active_actor
from workspaces.services._account_policy_reads import _allowed_batch

if TYPE_CHECKING:
    from django.db.models import Model, QuerySet
    from django.http import HttpRequest


class _ScopedReadOnlyAdmin(PolicyReadOnlyAdmin):
    """Derive the complete authorized queryset before Django counts or paginates."""

    def has_module_permission(self, request: HttpRequest) -> bool:
        try:
            _active_actor(self._credential(request))
            return True
        except Exception:
            return False

    def has_view_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        if obj is None:
            return self.has_module_permission(request)
        try:
            return _allowed_batch(
                self._credential(request),
                configured_authorization_provider(),
                self.policy_action,
                "workspace",
                (cast("WorkspaceQuotaPolicy | WorkspaceInvitation", obj).workspace.uuid,),
            )[0]
        except Exception:
            return False

    def get_queryset(self, request: HttpRequest) -> QuerySet[Model]:
        if not self.has_module_permission(request):
            raise PermissionDenied
        actor = self._credential(request)
        provider = configured_authorization_provider()
        query = self.model.objects.filter(
            workspace__organization__account__isnull=False, workspace__archived_at__isnull=True
        ).select_related("workspace")
        visible: list[int] = []
        cursor = 0
        while True:
            batch = tuple(query.filter(pk__gt=cursor).order_by("pk")[:100])
            if not batch:
                break
            try:
                allowed = _allowed_batch(
                    actor, provider, self.policy_action, "workspace", tuple(row.workspace.uuid for row in batch)
                )
            except Exception as exc:
                raise PermissionDenied from exc
            visible.extend(row.pk for row, permitted in zip(batch, allowed, strict=True) if permitted)
            cursor = batch[-1].pk
        return query.filter(pk__in=visible)


class PolicyWorkspaceQuotaAdmin(_ScopedReadOnlyAdmin):
    """Inspection is scoped; quota authoring has the canonical API equivalent."""

    model = WorkspaceQuotaPolicy
    policy_action = "workspace.manage_quota"
    fields = ("workspace", "resource", "limit", "mode", "revision", "updated_at")
    readonly_fields = fields


class PolicyWorkspaceInvitationAdmin(_ScopedReadOnlyAdmin):
    """Inspection never exposes raw invitation tokens or an alternate mutation path."""

    model = WorkspaceInvitation
    policy_action = "workspace.manage_invitations"
    fields = ("public_id", "workspace", "email", "expires_at", "accepted_at", "revoked_at")
    readonly_fields = fields
