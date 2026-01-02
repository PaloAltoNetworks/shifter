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
    list_display = ("id", "user", "agent", "ngfw", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email", "agent__name")
    raw_id_fields = ("user", "agent", "dc_agent", "ngfw")
