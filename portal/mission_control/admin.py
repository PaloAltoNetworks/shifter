"""Mission Control admin configuration."""

from django.contrib import admin

from .models import ActivityLog, AgentConfig, OperatingSystem, Range, UserProfile


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
    list_display = ("name", "user", "os", "original_filename", "created_at", "deleted_at")
    list_filter = ("os", "deleted_at", "created_at")
    search_fields = ("name", "user__email", "original_filename")
    raw_id_fields = ("user",)
    readonly_fields = ("s3_key", "sha256_hash", "file_size_bytes", "created_at")


@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "agent", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__email", "agent__name")
    raw_id_fields = ("user", "agent")


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
