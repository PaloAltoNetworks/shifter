"""Management admin configuration."""

from django.contrib import admin

from .models import ActivityLog, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "is_ctf_account", "must_change_password", "deleted_at", "anonymized_at")
    list_filter = ("is_ctf_account", "must_change_password", "deleted_at", "anonymized_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
    readonly_fields = ("is_ctf_account",)


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
