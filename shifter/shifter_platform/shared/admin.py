"""Administration registrations owned by the shared app."""

from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest

from shared.api_tokens import admin as _api_tokens_admin
from shared.models import AuditLog

__all__ = ["_api_tokens_admin"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Inspect audit events without permitting mutation."""

    list_display = [
        "timestamp",
        "action",
        "entity_type",
        "entity_id",
        "actor_type",
        "actor_id",
        "source_ip_display",
        "request_id_display",
    ]
    list_filter = [
        "action",
        "entity_type",
        "actor_type",
        ("source_ip", admin.EmptyFieldListFilter),
        "timestamp",
    ]
    search_fields = ["context", "request_id", "source_ip"]
    readonly_fields = [
        "entity_type",
        "entity_id",
        "action",
        "actor_type",
        "actor_id",
        "timestamp",
        "previous_state",
        "new_state",
        "context",
        "source_ip",
        "user_agent",
        "request_id",
    ]
    date_hierarchy = "timestamp"
    list_per_page = 50

    @admin.display(description="Source IP")
    def source_ip_display(self, obj: AuditLog) -> str:
        return obj.source_ip or "-"

    @admin.display(description="Request ID")
    def request_id_display(self, obj: AuditLog) -> str:
        if obj.request_id:
            return obj.request_id[:12] + "..." if len(obj.request_id) > 12 else obj.request_id
        return "-"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AuditLog | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AuditLog | None = None) -> bool:
        return False
