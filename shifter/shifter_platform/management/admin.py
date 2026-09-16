"""Management admin configuration."""

from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from .models import ActivityLog, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin for extended user profiles (soft-delete and anonymization state)."""

    list_display = ("user", "is_ctf_account", "must_change_password", "deleted_at", "anonymized_at")
    list_filter = ("is_ctf_account", "must_change_password", "deleted_at", "anonymized_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)
    readonly_fields = ("is_ctf_account",)


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    """Read-only admin for the activity/audit log."""

    list_display = ("action", "user", "timestamp")
    list_filter = ("action", "timestamp")
    search_fields = ("action", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("action", "user", "timestamp", "metadata")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        return False
