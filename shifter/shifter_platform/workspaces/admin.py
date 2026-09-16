"""Superuser-only operational escape hatches for the workspaces domain.

Deep, rarely used administration stays in Django admin rather than the SPA
(PLAT-241). Invitation diagnosis is read-only; quota policy authoring is the
one write escape hatch and routes every change through the superuser-only
``workspaces.services`` command so validation and strict audit cannot be
bypassed (PLAT-239).
"""

from typing import TYPE_CHECKING, cast

from django.contrib import admin
from django.forms import ModelForm
from django.http import HttpRequest
from django.utils import timezone

from workspaces import services
from workspaces.models import WorkspaceInvitation, WorkspaceQuotaPolicy

if TYPE_CHECKING:
    from django.contrib.auth.models import User


@admin.register(WorkspaceInvitation)
class WorkspaceInvitationAdmin(admin.ModelAdmin):
    """Superuser-only inspection; lifecycle mutations stay behind services."""

    fields = (
        "public_id",
        "workspace",
        "email",
        "role",
        "status",
        "expires_at",
        "created_by",
        "accepted_by",
        "accepted_at",
        "revoked_at",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields
    list_display = ("public_id", "workspace", "role", "status", "expires_at", "created_at")
    list_filter = ("role", "accepted_at", "revoked_at")
    ordering = ("-created_at",)
    actions = None

    @admin.display(description="Status")
    def status(self, invitation: WorkspaceInvitation) -> str:
        status = "pending"
        if invitation.accepted_at is not None:
            status = "accepted"
        elif invitation.revoked_at is not None:
            status = "revoked"
        elif invitation.expires_at <= timezone.now():
            status = "expired"
        return status

    def has_view_permission(self, request: HttpRequest, obj: WorkspaceInvitation | None = None) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: WorkspaceInvitation | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: WorkspaceInvitation | None = None) -> bool:
        return False


@admin.register(WorkspaceQuotaPolicy)
class WorkspaceQuotaPolicyAdmin(admin.ModelAdmin):
    """Superuser-only quota policy authoring; every write goes through the service.

    A quota is a platform guardrail, so authoring is authorized only by a
    superuser session (never a workspace/organization role). ``save_model``
    delegates to ``workspaces.services.set_workspace_quota_policy``, which
    validates, upserts under the workspace mutex, bumps the revision, and writes a
    strict audit event — the admin never performs a raw model save. Deletion is
    disabled to keep every change audited; lower a limit rather than removing it.
    """

    fields = ("workspace", "resource", "limit", "mode", "revision", "created_at", "updated_at")
    list_display = ("workspace", "resource", "limit", "mode", "revision", "updated_at")
    list_filter = ("resource", "mode")
    ordering = ("-updated_at",)
    autocomplete_fields = ()

    def get_readonly_fields(self, request: HttpRequest, obj: WorkspaceQuotaPolicy | None = None) -> tuple[str, ...]:
        # The policy identity (workspace, resource) is fixed after creation:
        # ``save_model`` upserts by these values, so allowing them to change on an
        # existing row would silently create/update a *different* policy and leave
        # the original in force. Only limit/mode are editable on a change.
        base = ("revision", "created_at", "updated_at")
        if obj is not None:
            return ("workspace", "resource", *base)
        return base

    def _admin_audit(self, request: HttpRequest) -> services.WorkspaceQuotaAuditContext:
        return services.WorkspaceQuotaAuditContext(
            actor_type="user",
            actor_id=getattr(request.user, "pk", None),
            source_ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            request_id=request.META.get("HTTP_X_REQUEST_ID", "")[:64],
        )

    def save_model(self, request: HttpRequest, obj: WorkspaceQuotaPolicy, form: ModelForm, change: bool) -> None:
        # Route through the superuser-only service (validation + strict audit +
        # revision bump) instead of a raw save, then reflect the persisted row back
        # onto the admin's object so its change log resolves.
        services.set_workspace_quota_policy(
            cast("User", request.user),
            obj.workspace.uuid,
            obj.resource,
            obj.limit,
            obj.mode,
            audit=self._admin_audit(request),
        )
        persisted = WorkspaceQuotaPolicy.objects.get(workspace=obj.workspace, resource=obj.resource)
        obj.pk = persisted.pk
        obj.revision = persisted.revision

    def has_module_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request: HttpRequest, obj: WorkspaceQuotaPolicy | None = None) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request: HttpRequest, obj: WorkspaceQuotaPolicy | None = None) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request: HttpRequest, obj: WorkspaceQuotaPolicy | None = None) -> bool:
        return False
