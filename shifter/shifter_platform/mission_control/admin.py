"""Mission Control admin configuration."""

from django.contrib import admin

from .models import (
    AgentConfig,
    NGFWDeploymentProfile,
    OperatingSystem,
    Range,
    SCMCredential,
    UserNGFW,
)


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


@admin.register(SCMCredential)
class SCMCredentialAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "scm_folder_name", "sls_region", "expires_at", "deleted_at")
    list_filter = ("sls_region", "deleted_at", "created_at")
    search_fields = ("name", "user__email", "scm_folder_name")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(NGFWDeploymentProfile)
class NGFWDeploymentProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "expires_at", "last_used_at", "deleted_at")
    list_filter = ("deleted_at", "created_at")
    search_fields = ("name", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(UserNGFW)
class UserNGFWAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "status", "serial_number", "created_at", "deleted_at")
    list_filter = ("status", "deleted_at", "created_at")
    search_fields = ("name", "user__email", "serial_number", "instance_id")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "agent", "ngfw", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email", "agent__name")
    raw_id_fields = ("user", "agent", "dc_agent", "ngfw")
