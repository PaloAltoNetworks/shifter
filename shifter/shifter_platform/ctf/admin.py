"""Django admin configuration for CTF models.

Provides admin interfaces for managing CTF events, challenges,
participants, teams, and related entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils.html import format_html

from ctf.models import (
    CTFAward,
    CTFChallenge,
    CTFChallengeFile,
    CTFChallengePrerequisite,
    CTFEvent,
    CTFNotification,
    CTFParticipant,
    CTFScheduledTask,
    CTFSubmission,
    CTFTeam,
)

if TYPE_CHECKING:
    from django.db import models as _models
    from django.db.models import QuerySet
    from django.http import HttpRequest


class SoftDeleteAdminMixin:
    """Mixin for handling soft-deleted records in admin."""

    model: type[_models.Model]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Include soft-deleted records in admin queryset."""
        return self.model.all_objects.all()  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# Inline Admins
# -----------------------------------------------------------------------------


class CTFChallengeInline(admin.TabularInline):
    """Inline admin for challenges within an event."""

    model = CTFChallenge
    extra = 0
    fields = ["name", "category", "points", "difficulty", "order"]
    readonly_fields = []
    show_change_link = True
    ordering = ["category", "order"]


class CTFParticipantInline(admin.TabularInline):
    """Inline admin for participants within an event."""

    model = CTFParticipant
    extra = 0
    fields = ["name", "email", "status", "team", "range_status"]
    readonly_fields = ["range_status"]
    show_change_link = True
    ordering = ["name"]


class CTFTeamInline(admin.TabularInline):
    """Inline admin for teams within an event."""

    model = CTFTeam
    extra = 0
    fields = ["name", "invite_code", "captain"]
    readonly_fields = ["invite_code"]
    show_change_link = True


class CTFScheduledTaskInline(admin.TabularInline):
    """Inline admin for scheduled tasks within an event."""

    model = CTFScheduledTask
    extra = 0
    fields = ["task_type", "scheduled_for", "status", "executed_at"]
    readonly_fields = ["status", "executed_at"]
    show_change_link = True
    ordering = ["scheduled_for"]


class CTFChallengeFileInline(admin.TabularInline):
    """Inline admin for file attachments within a challenge."""

    model = CTFChallengeFile
    extra = 0
    fields = ["filename", "display_name", "file_size_bytes", "content_type", "order"]
    readonly_fields = ["filename", "file_size_bytes", "content_type"]
    show_change_link = True
    ordering = ["order", "created_at"]


class CTFChallengePrerequisiteInline(admin.TabularInline):
    """Inline admin for prerequisites within a challenge."""

    model = CTFChallengePrerequisite
    fk_name = "challenge"
    extra = 0
    fields = ["required_challenge"]
    show_change_link = True
    ordering = ["created_at"]


class CTFSubmissionInline(admin.TabularInline):
    """Inline admin for submissions within a challenge or participant."""

    model = CTFSubmission
    extra = 0
    fields = ["participant", "submitted_flag", "is_correct", "points_awarded", "submitted_at"]
    readonly_fields = ["submitted_at"]
    show_change_link = True
    ordering = ["-submitted_at"]


class CTFAwardInline(admin.TabularInline):
    """Inline admin for awards within an event or participant."""

    model = CTFAward
    extra = 0
    fields = ["participant", "points", "reason", "granted_by", "created_at"]
    readonly_fields = ["created_at"]
    show_change_link = True
    ordering = ["-created_at"]


# -----------------------------------------------------------------------------
# Model Admins
# -----------------------------------------------------------------------------


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
            "Hints",
            {
                "fields": ["hint", "hint_penalty"],
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


@admin.register(CTFTeam)
class CTFTeamAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF teams."""

    list_display = [
        "name",
        "event",
        "member_count_display",
        "total_score_display",
        "captain",
        "invite_code",
        "is_deleted_display",
    ]
    list_filter = ["event", "deleted_at"]
    search_fields = ["name", "event__name", "captain__name"]
    ordering = ["event", "name"]
    readonly_fields = ["id", "invite_code", "created_at", "updated_at", "deleted_at"]

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "name", "captain"],
            },
        ),
        (
            "Team Access",
            {
                "fields": ["invite_code"],
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
        """Annotate queryset with member count and score (submissions + awards)."""
        qs = super().get_queryset(request)
        return qs.annotate(
            _member_count=Count("members", distinct=True),
            _submission_score=Coalesce(
                Sum(
                    "members__submissions__points_awarded",
                    filter=Q(members__submissions__is_correct=True),
                ),
                0,
            ),
            _award_score=Coalesce(Sum("members__awards__points"), 0),
            _total_score=F("_submission_score") + F("_award_score"),
        )

    @admin.display(description="Members", ordering="_member_count")
    def member_count_display(self, obj: CTFTeam) -> int:
        """Display member count."""
        return getattr(obj, "_member_count", obj.member_count)

    @admin.display(description="Score", ordering="_total_score")
    def total_score_display(self, obj: CTFTeam) -> int:
        """Display total team score."""
        return getattr(obj, "_total_score", obj.total_score)

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFTeam) -> bool:
        """Display soft delete status."""
        return obj.is_deleted


@admin.register(CTFParticipant)
class CTFParticipantAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF participants."""

    list_display = [
        "name",
        "email",
        "event",
        "status",
        "team",
        "total_score_display",
        "solved_count_display",
        "is_registered",
        "range_status",
        "is_deleted_display",
    ]
    list_filter = ["status", "event", "team", "deleted_at"]
    search_fields = ["name", "email", "event__name", "user__email"]
    ordering = ["event", "name"]
    readonly_fields = [
        "id",
        "invite_token",
        "invite_token_expires",
        "created_at",
        "updated_at",
        "deleted_at",
        "registered_at",
        "invited_at",
        "last_active_at",
        "total_score_display",
        "solved_count_display",
    ]

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "name", "email", "user", "status"],
            },
        ),
        (
            "Team",
            {
                "fields": ["team"],
            },
        ),
        (
            "Range",
            {
                "fields": ["range_instance_id", "range_status"],
            },
        ),
        (
            "Registration",
            {
                "fields": [
                    "cognito_sub",
                    "invite_token",
                    "invite_token_expires",
                    "invited_at",
                    "registered_at",
                    "last_active_at",
                ],
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

    inlines = [CTFSubmissionInline, CTFAwardInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Annotate queryset with score (submissions + awards) and solve count."""
        qs = super().get_queryset(request)
        return qs.annotate(
            _submission_score=Coalesce(
                Sum(
                    "submissions__points_awarded",
                    filter=Q(submissions__is_correct=True),
                ),
                0,
            ),
            _award_score=Coalesce(Sum("awards__points"), 0),
            _total_score=F("_submission_score") + F("_award_score"),
            _solved_count=Count(
                "submissions",
                filter=Q(submissions__is_correct=True),
            ),
        )

    @admin.display(description="Score", ordering="_total_score")
    def total_score_display(self, obj: CTFParticipant) -> int:
        """Display total score."""
        return getattr(obj, "_total_score", obj.total_score)

    @admin.display(description="Solved", ordering="_solved_count")
    def solved_count_display(self, obj: CTFParticipant) -> int:
        """Display solved challenge count."""
        return getattr(obj, "_solved_count", obj.solved_challenge_count)

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFParticipant) -> bool:
        """Display soft delete status."""
        return obj.is_deleted


@admin.register(CTFSubmission)
class CTFSubmissionAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF submissions."""

    list_display = [
        "participant",
        "challenge",
        "is_correct_display",
        "points_awarded",
        "attempt_number",
        "hint_used",
        "submitted_at",
        "ip_address",
    ]
    list_filter = ["is_correct", "hint_used", "challenge__event", "submitted_at"]
    search_fields = [
        "participant__name",
        "participant__email",
        "challenge__name",
        "submitted_flag",
    ]
    ordering = ["-submitted_at"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at", "submitted_at"]
    date_hierarchy = "submitted_at"

    fieldsets = [
        (
            None,
            {
                "fields": ["participant", "challenge"],
            },
        ),
        (
            "Submission",
            {
                "fields": [
                    "submitted_flag",
                    "is_correct",
                    "points_awarded",
                    "attempt_number",
                ],
            },
        ),
        (
            "Details",
            {
                "fields": ["hint_used", "ip_address", "submitted_at"],
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

    @admin.display(description="Correct", boolean=True)
    def is_correct_display(self, obj: CTFSubmission) -> bool:
        """Display correctness as icon."""
        return obj.is_correct


@admin.register(CTFAward)
class CTFAwardAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF awards."""

    list_display = [
        "participant",
        "event",
        "points",
        "reason_short",
        "granted_by",
        "created_at",
        "is_deleted_display",
    ]
    list_filter = ["event", "granted_by", "deleted_at"]
    search_fields = ["participant__name", "participant__email", "reason", "event__name"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at"]

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "participant", "points", "reason", "granted_by"],
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

    @admin.display(description="Reason")
    def reason_short(self, obj: CTFAward) -> str:
        """Display truncated reason."""
        return obj.reason[:80] + "..." if len(obj.reason) > 80 else obj.reason

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFAward) -> bool:
        """Display soft delete status."""
        return obj.is_deleted


@admin.register(CTFNotification)
class CTFNotificationAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF notifications."""

    list_display = [
        "subject",
        "event",
        "notification_type",
        "status",
        "recipient_filter",
        "sent_count",
        "scheduled_at",
        "sent_at",
        "created_by",
    ]
    list_filter = ["status", "notification_type", "recipient_filter", "event"]
    search_fields = ["subject", "body", "event__name"]
    ordering = ["-created_at"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at", "sent_at", "sent_count"]

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "notification_type", "created_by"],
            },
        ),
        (
            "Content",
            {
                "fields": ["subject", "body"],
            },
        ),
        (
            "Recipients",
            {
                "fields": ["recipient_filter", "recipient_emails"],
            },
        ),
        (
            "Schedule",
            {
                "fields": ["status", "scheduled_at", "sent_at", "sent_count"],
            },
        ),
        (
            "Errors",
            {
                "fields": ["error_message"],
                "classes": ["collapse"],
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


@admin.register(CTFScheduledTask)
class CTFScheduledTaskAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF scheduled tasks."""

    list_display = [
        "task_type",
        "event",
        "status_display",
        "scheduled_for",
        "executed_at",
        "is_due",
    ]
    list_filter = ["status", "task_type", "event"]
    search_fields = ["event__name"]
    ordering = ["scheduled_for"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at", "executed_at"]
    date_hierarchy = "scheduled_for"

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "task_type", "status"],
            },
        ),
        (
            "Schedule",
            {
                "fields": ["scheduled_for", "executed_at"],
            },
        ),
        (
            "Details",
            {
                "fields": ["metadata", "error_message"],
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

    @admin.display(description="Status")
    def status_display(self, obj: CTFScheduledTask) -> str:
        """Display status with color coding."""
        colors = {
            "pending": "orange",
            "running": "blue",
            "completed": "green",
            "failed": "red",
            "cancelled": "gray",
        }
        color = colors.get(obj.status, "black")
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.status.upper(),
        )


@admin.register(CTFChallengeFile)
class CTFChallengeFileAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF challenge files."""

    list_display = [
        "filename",
        "display_name",
        "challenge",
        "file_size_bytes",
        "content_type",
        "order",
        "is_deleted_display",
    ]
    list_filter = ["content_type", "challenge__event", "deleted_at"]
    search_fields = ["filename", "display_name", "challenge__name"]
    ordering = ["challenge", "order"]
    readonly_fields = ["id", "s3_key", "sha256_hash", "file_size_bytes", "created_at", "updated_at", "deleted_at"]

    fieldsets = [
        (
            None,
            {
                "fields": ["challenge", "filename", "display_name"],
            },
        ),
        (
            "File Details",
            {
                "fields": ["s3_key", "file_size_bytes", "content_type", "sha256_hash", "order"],
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

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFChallengeFile) -> bool:
        """Display soft delete status."""
        return obj.is_deleted


@admin.register(CTFChallengePrerequisite)
class CTFChallengePrerequisiteAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for CTF challenge prerequisites."""

    list_display = [
        "challenge",
        "required_challenge",
        "is_deleted_display",
    ]
    list_filter = ["challenge__event", "deleted_at"]
    search_fields = ["challenge__name", "required_challenge__name"]
    ordering = ["challenge"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at"]

    fieldsets = [
        (
            None,
            {
                "fields": ["challenge", "required_challenge"],
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

    @admin.display(description="Deleted", boolean=True)
    def is_deleted_display(self, obj: CTFChallengePrerequisite) -> bool:
        """Display soft delete status."""
        return obj.is_deleted
