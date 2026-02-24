"""Django admin configuration for Risk Register."""

from django.contrib import admin

from risk_register.models import APIKey, AuditLog, Comment, Risk


@admin.register(Risk)
class RiskAdmin(admin.ModelAdmin):
    """Admin interface for Risk model."""

    list_display = [
        "title",
        "severity",
        "status",
        "risk_score",
        "created_at",
        "is_deleted",
    ]
    list_filter = ["severity", "status", "stride_categories", "deleted_at"]
    search_fields = ["title", "description", "affected_assets"]
    readonly_fields = ["created_at", "updated_at", "risk_score", "comment_count"]
    date_hierarchy = "created_at"

    fieldsets = [
        (None, {"fields": ["title", "description", "severity", "status"]}),
        (
            "Threat Modeling",
            {
                "fields": [
                    "stride_categories",
                    "likelihood_score",
                    "impact_score",
                    "attack_vector",
                    "affected_assets",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Resolution",
            {
                "fields": ["mitigation_status", "resolution_reason"],
                "classes": ["collapse"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["created_at", "updated_at", "deleted_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    @admin.display(boolean=True)
    def is_deleted(self, obj):
        return obj.is_deleted


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """Admin interface for Comment model."""

    list_display = ["risk", "author_display", "created_at", "is_deleted"]
    list_filter = ["deleted_at", "created_at"]
    search_fields = ["content", "risk__title"]
    readonly_fields = ["created_at", "author_display"]
    raw_id_fields = ["risk", "author_user", "author_apikey", "parent_comment"]

    @admin.display(boolean=True)
    def is_deleted(self, obj):
        return obj.is_deleted


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    """Admin interface for APIKey model."""

    list_display = [
        "name",
        "display_key",
        "created_by",
        "created_at",
        "last_used_at",
        "is_active",
    ]
    list_filter = ["revoked_at", "created_at"]
    search_fields = ["name", "prefix"]
    readonly_fields = ["prefix", "key_hash", "created_at", "last_used_at"]
    raw_id_fields = ["created_by"]

    @admin.display(boolean=True)
    def is_active(self, obj):
        return obj.is_active


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin interface for AuditLog model.

    Read-only interface for viewing audit logs. No add/change/delete permitted.
    """

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

    fieldsets = [
        (
            "Event",
            {
                "fields": ["action", "entity_type", "entity_id", "timestamp"],
            },
        ),
        (
            "Actor",
            {
                "fields": ["actor_type", "actor_id"],
            },
        ),
        (
            "State",
            {
                "fields": ["previous_state", "new_state", "context"],
                "classes": ["collapse"],
            },
        ),
        (
            "Request Context",
            {
                "fields": ["source_ip", "user_agent", "request_id"],
                "classes": ["collapse"],
            },
        ),
    ]

    @admin.display(description="Source IP")
    def source_ip_display(self, obj):
        return obj.source_ip or "-"

    @admin.display(description="Request ID")
    def request_id_display(self, obj):
        if obj.request_id:
            return obj.request_id[:12] + "..." if len(obj.request_id) > 12 else obj.request_id
        return "-"

    def has_add_permission(self, request):
        """Prevent manual creation of audit logs."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent editing of audit logs."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of audit logs."""
        return False
