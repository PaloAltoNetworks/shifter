"""Engine admin configuration."""

from django.contrib import admin

from engine.models import Range, SubnetAllocation


@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "scenario_id", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)

    @admin.display(description="Scenario")
    def scenario_id(self, obj):
        if obj.range_config:
            return obj.range_config.get("scenario_id", "—")
        return "—"


@admin.register(SubnetAllocation)
class SubnetAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "vpc_id",
        "cidr",
        "subnet_size",
        "range_id",
        "request_id",
        "created_at",
    )
    list_filter = ("vpc_id", "subnet_size")
    search_fields = ("cidr", "request_id", "vpc_id")
    readonly_fields = ("created_at",)
