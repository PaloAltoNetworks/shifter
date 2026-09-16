"""Engine admin configuration."""

from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest

from engine.models import (
    CapacityAssessment,
    CapacityDeclaration,
    CapacityDraw,
    CapacityReservation,
    Range,
    SubnetAllocation,
)
from shared.schemas.persistence import unwrap_persisted_spec


@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    """Operator visibility for provisioned ranges."""

    list_display = ("id", "user", "scenario_id", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__email",)
    raw_id_fields = ("user",)

    @admin.display(description="Scenario")
    def scenario_id(self, obj: Range) -> str:
        if obj.range_config:
            return unwrap_persisted_spec(obj.range_config).get("scenario_id", "—")
        return "—"


@admin.register(SubnetAllocation)
class SubnetAllocationAdmin(admin.ModelAdmin):
    """Operator visibility for VPC subnet allocations."""

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


@admin.register(CapacityDeclaration)
class CapacityDeclarationAdmin(admin.ModelAdmin):
    """Operator visibility for declared event capacity (CTF-908)."""

    list_display = (
        "event_name",
        "event_ref",
        "expected_concurrent_ranges",
        "cohort_size",
        "window_start",
        "declared_at",
    )
    list_filter = ("source", "declared_at")
    search_fields = ("event_name", "event_ref")
    readonly_fields = [f.name for f in CapacityDeclaration._meta.fields]


@admin.register(CapacityAssessment)
class CapacityAssessmentAdmin(admin.ModelAdmin):
    """Operator visibility for capacity-admission decisions (PLAT-201).

    Fully read-only: assessments are an append-only record of what was decided,
    so editing one in admin would falsify history rather than change anything.
    """

    list_display = (
        "event_ref",
        "partition_name",
        "outcome",
        "policy_version",
        "observed_at",
        "assessed_at",
    )
    list_filter = ("outcome", "partition_name", "assessed_at")
    search_fields = ("event_ref", "partition_name", "policy_version")
    readonly_fields = [f.name for f in CapacityAssessment._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Assessments are written by the engine, never by hand."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        """Assessments are immutable history."""
        return False


@admin.register(CapacityReservation)
class CapacityReservationAdmin(admin.ModelAdmin):
    """Operator visibility for committed capacity reservations (PLAT-201)."""

    list_display = (
        "event_ref",
        "partition_name",
        "metric_name",
        "amount",
        "consumed",
        "unit_amount",
        "enforcement",
        "window_start",
        "window_end",
        "released_at",
    )
    list_filter = ("partition_name", "metric_name", "released_at")
    search_fields = ("event_ref", "partition_name", "metric_name")
    readonly_fields = [f.name for f in CapacityReservation._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Reservations are created by assessment, never by hand."""
        return False


@admin.register(CapacityDraw)
class CapacityDrawAdmin(admin.ModelAdmin):
    """Operator visibility for per-range capacity draws (PLAT-201).

    Read-only. This is the ledger that shows where an event's budget actually
    went, and it is what an operator reads when a budget looks exhausted.
    """

    list_display = ("event_ref", "draw_key", "request_id", "amount", "created_at", "released_at")
    list_filter = ("released_at", "created_at")
    search_fields = ("event_ref", "draw_key", "request_id")
    readonly_fields = [f.name for f in CapacityDraw._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Draws are created by admission, never by hand."""
        return False

    def has_change_permission(self, request: HttpRequest, obj: Model | None = None) -> bool:
        """The ledger is not hand-editable."""
        return False
