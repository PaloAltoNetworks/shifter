"""Admin classes for CTF events, challenges, and brackets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.db.models import Count, Q

from ctf.models import CTFBracket, CTFChallenge, CTFEvent

from ._base import SoftDeleteAdminMixin
from ._inlines import (
    CTFAwardInline,
    CTFChallengeFileInline,
    CTFChallengeInline,
    CTFChallengePrerequisiteInline,
    CTFParticipantInline,
    CTFScheduledTaskInline,
    CTFSubmissionInline,
    CTFTeamInline,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


@admin.register(CTFEvent)
class CTFEventAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF events."""

    list_display = [
        "name",
        "status",
        "event_start",
        "event_end",
        "participant_count_display",
        "challenge_count_display",
        "team_mode",
        "created_by",
        "is_deleted_display",
    ]
    list_filter = ["status", "team_mode", "auto_cleanup", "deleted_at"]
    search_fields = ["name", "description", "created_by__email"]
    date_hierarchy = "event_start"
    ordering = ["-event_start"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "participant_count_display",
        "challenge_count_display",
    ]

    fieldsets = [
        (
            None,
            {
                "fields": ["name", "description", "created_by", "status"],
            },
        ),
        (
            "Schedule",
            {
                "fields": [
                    "event_start",
                    "event_end",
                    "registration_deadline",
                    "range_spinup_minutes",
                ],
            },
        ),
        (
            "Configuration",
            {
                "fields": [
                    "scenario_id",
                    "team_mode",
                    "team_size_limit",
                    "max_participants",
                    "scoring_mode",
                ],
            },
        ),
        (
            "Cleanup",
            {
                "fields": ["auto_cleanup", "cleanup_delay_hours"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["id", "created_at", "updated_at", "deleted_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    inlines = [CTFChallengeInline, CTFTeamInline, CTFParticipantInline, CTFAwardInline, CTFScheduledTaskInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate queryset with counts."""
        qs = super().get_queryset(request)
        return qs.annotate(
            _participant_count=Count("participants", distinct=True),
            _challenge_count=Count("challenges", distinct=True),
        )

    @admin.display(description="Participants", ordering="_participant_count")
    def participant_count_display(self, obj: CTFEvent) -> int:
        """Display participant count."""
        return getattr(obj, "_participant_count", obj.participant_count)

    @admin.display(description="Challenges", ordering="_challenge_count")
    def challenge_count_display(self, obj: CTFEvent) -> int:
        """Display challenge count."""
        return getattr(obj, "_challenge_count", obj.challenge_count)

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFEvent) -> bool:
        """Display soft delete status."""
        return obj.is_deleted


@admin.register(CTFChallenge)
class CTFChallengeAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF challenges."""

    list_display = [
        "name",
        "event",
        "category",
        "points",
        "difficulty",
        "solve_count_display",
        "is_released",
        "order",
        "is_deleted_display",
    ]
    list_filter = ["category", "difficulty", "event", "deleted_at"]
    search_fields = ["name", "description", "event__name"]
    ordering = ["event", "category", "order"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at", "solve_count_display"]

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "name", "description"],
            },
        ),
        (
            "Challenge Details",
            {
                "fields": ["category", "points", "difficulty", "order"],
            },
        ),
        (
            "Flag",
            {
                "fields": ["flag_hash", "flag_format"],
            },
        ),
        (
            "Limits",
            {
                "fields": ["max_attempts", "release_time"],
            },
        ),
        (
            "Connection",
            {
                "fields": ["target_instance_name", "target_port"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["id", "created_at", "updated_at", "deleted_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    inlines = [CTFChallengeFileInline, CTFChallengePrerequisiteInline, CTFSubmissionInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate queryset with solve count."""
        qs = super().get_queryset(request)
        return qs.annotate(_solve_count=Count("submissions", filter=Q(submissions__is_correct=True)))

    @admin.display(description="Solves", ordering="_solve_count")
    def solve_count_display(self, obj: CTFChallenge) -> int:
        """Display solve count."""
        return getattr(obj, "_solve_count", obj.solve_count)

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFChallenge) -> bool:
        """Display soft delete status."""
        return obj.is_deleted


@admin.register(CTFBracket)
class CTFBracketAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF brackets."""

    list_display = [
        "name",
        "event",
        "display_order",
        "participant_count_display",
        "is_deleted_display",
    ]
    list_filter = ["event", "deleted_at"]
    search_fields = ["name", "event__name"]
    ordering = ["event", "display_order", "name"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at"]

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "name", "description", "display_order"],
            },
        ),
        (
            "Metadata",
            {
                "fields": ["id", "created_at", "updated_at", "deleted_at"],
                "classes": ["collapse"],
            },
        ),
    ]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate queryset with participant count."""
        qs = super().get_queryset(request)
        return qs.annotate(_participant_count=Count("participants", distinct=True))

    @admin.display(description="Participants", ordering="_participant_count")
    def participant_count_display(self, obj: CTFBracket) -> int:
        """Display participant count."""
        return getattr(obj, "_participant_count", obj.participant_count)

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFBracket) -> bool:
        """Display soft delete status."""
        return obj.is_deleted
