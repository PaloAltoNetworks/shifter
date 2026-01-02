"""CMS admin configuration."""

from django.contrib import admin

from cms.models import AgentConfig, OperatingSystem, UserNGFW


@admin.register(OperatingSystem)
class OperatingSystemAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "extensions")
    search_fields = ("name", "slug")
    ordering = ("name",)


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


@admin.register(UserNGFW)
class UserNGFWAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "status", "serial_number", "created_at", "deleted_at")
    list_filter = ("status", "deleted_at", "created_at")
    search_fields = ("name", "user__email", "serial_number", "instance_id")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)
