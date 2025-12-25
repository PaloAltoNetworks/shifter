"""Mission Control admin configuration."""

from django.contrib import admin

from .models import ActivityLog, AgentConfig, NGFWConfig, OperatingSystem, Range, UserProfile


@admin.register(OperatingSystem)
class OperatingSystemAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "extensions")
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "deleted_at", "anonymized_at")
    list_filter = ("deleted_at", "anonymized_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)


@admin.register(AgentConfig)
class AgentConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "os",
        "original_filename",
        "created_at",
        "deleted_at",
    )
    list_filter = ("os", "deleted_at", "created_at")
    search_fields = ("name", "user__email", "original_filename")
    raw_id_fields = ("user",)
    readonly_fields = ("s3_key", "sha256_hash", "file_size_bytes", "created_at")


@admin.register(NGFWConfig)
class NGFWConfigAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "panorama_server",
        "created_at",
        "deleted_at",
    )
    list_filter = ("deleted_at", "created_at")
    search_fields = ("name", "user__email", "panorama_server")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)
    fieldsets = (
        (None, {"fields": ("user", "name")}),
        (
            "Panorama Configuration",
            {
                "fields": (
                    "panorama_server",
                    "vm_auth_key",
                    "panorama_server_2",
                    "template_stack",
                    "device_group",
                )
            },
        ),
        ("Metadata", {"fields": ("created_at", "deleted_at")}),
    )


@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "agent", "status", "ngfw_enabled", "created_at")
    list_filter = ("status", "ngfw_enabled", "created_at")
    search_fields = ("user__email", "agent__name")
    raw_id_fields = ("user", "agent", "ngfw_config")
    readonly_fields = ("ngfw_instance_id", "ngfw_untrust_ip", "ngfw_trust_ip")
    fieldsets = (
        (None, {"fields": ("user", "agent", "status")}),
        ("NGFW", {"fields": ("ngfw_enabled", "ngfw_config", "ngfw_instance_id", "ngfw_untrust_ip", "ngfw_trust_ip")}),
        ("Timestamps", {"fields": ("created_at", "ready_at", "destroyed_at")}),
    )


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("action", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("action", "user", "timestamp", "metadata")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
