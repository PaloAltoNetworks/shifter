"""Engine admin configuration."""

from django.contrib import admin

from engine.models import Range, UserNGFW


@admin.register(UserNGFW)
class UserNGFWAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "status", "serial_number", "created_at", "deleted_at")
    list_filter = ("status", "deleted_at", "created_at")
    search_fields = ("name", "user__email", "serial_number", "instance_id")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)


@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "scenario_id", "ngfw", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user", "ngfw")

    @admin.display(description="Scenario")
    def scenario_id(self, obj):
        if obj.range_config:
            return obj.range_config.get("scenario_id", "—")
        return "—"
