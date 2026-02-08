"""CMS admin configuration."""

from django.contrib import admin

from cms.models import AgentConfig, OperatingSystem, Scenario, ScenarioMetadata, Subnet


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


@admin.register(Subnet)
class SubnetAdmin(admin.ModelAdmin):
    list_display = ("name", "request", "status", "created_at", "deleted_at")
    list_filter = ("status", "deleted_at", "created_at")
    search_fields = ("name", "id")
    readonly_fields = ("id", "created_at", "deleted_at")


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "scenario_id", "created_by", "created_at", "updated_at", "deleted_at")
    list_filter = ("deleted_at", "created_at")
    search_fields = ("name", "scenario_id", "description")
    raw_id_fields = ("created_by", "updated_by")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ScenarioMetadata)
class ScenarioMetadataAdmin(admin.ModelAdmin):
    list_display = ("scenario_id", "enabled", "staff_only", "updated_by", "updated_at")
    list_filter = ("enabled", "staff_only")
    search_fields = ("scenario_id",)
    raw_id_fields = ("updated_by",)
    readonly_fields = ("updated_at",)
