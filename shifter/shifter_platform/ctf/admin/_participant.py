"""Admin classes for CTF teams, participants, submissions, and awards."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import admin
from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce

from ctf.models import CTFAward, CTFParticipant, CTFSubmission, CTFTeam

from ._base import SoftDeleteAdminMixin
from ._inlines import CTFAwardInline, CTFSubmissionInline

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest


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
        """Annotate queryset with member count and score (submissions + awards).

        Codex review (#765/#768/#769 cycle 5 + cycle 7):
          - Cycle 5: aggregating submissions and awards on the same
            `members__*` relation in one annotate() produced a cartesian
            product when a member had both a solve and an award.
            Pre-aggregate via independent subqueries on CTFSubmission
            and CTFAward.
          - Cycle 7: apply `eligible_participant_q()` so disqualified or
            unregistered members' solves/awards are excluded from the
            admin team list — same eligibility predicate used by the
            scoreboard.
        """
        from django.db.models import IntegerField, OuterRef, Subquery

        from ctf.models import CTFAward, CTFSubmission
        from ctf.services.participant import eligible_participant_q

        qs = super().get_queryset(request)
        member_eligibility_via_participant = eligible_participant_q("participant__")
        submission_subq = (
            CTFSubmission.objects.filter(
                participant__team_id=OuterRef("pk"),
                is_correct=True,
            )
            .filter(member_eligibility_via_participant)
            .order_by()
            .values("participant__team_id")
            .annotate(t=Coalesce(Sum("points_awarded"), 0))
            .values("t")
        )
        award_subq = (
            CTFAward.objects.filter(participant__team_id=OuterRef("pk"))
            .filter(member_eligibility_via_participant)
            .order_by()
            .values("participant__team_id")
            .annotate(t=Coalesce(Sum("points"), 0))
            .values("t")
        )
        return qs.annotate(
            _member_count=Count("members", filter=eligible_participant_q("members__"), distinct=True),
            _submission_score=Coalesce(Subquery(submission_subq, output_field=IntegerField()), 0),
            _award_score=Coalesce(Subquery(award_subq, output_field=IntegerField()), 0),
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
        "bracket",
        "total_score_display",
        "solved_count_display",
        "is_registered",
        "range_status",
        "is_deleted_display",
    ]
    list_filter = ["status", "event", "team", "bracket", "deleted_at"]
    search_fields = ["name", "email", "event__name", "user__email"]
    ordering = ["event", "name"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "registered_at",
        "login_info_sent_at",
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
            "Team & Bracket",
            {
                "fields": ["team", "bracket"],
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
                    "login_info_sent_at",
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
        """Annotate queryset with score (submissions + awards) and solve count.

        Codex review (#765 cycle 6): same cartesian-product fix as the
        team admin and team scoreboard — pre-aggregate submissions and
        awards via subqueries so a participant with both a solve and an
        award doesn't get double-counted via the join.
        """
        from django.db.models import IntegerField, OuterRef, Subquery

        from ctf.models import CTFAward, CTFSubmission

        qs = super().get_queryset(request)
        submission_subq = (
            CTFSubmission.objects.filter(participant_id=OuterRef("pk"), is_correct=True)
            .order_by()
            .values("participant_id")
            .annotate(t=Coalesce(Sum("points_awarded"), 0))
            .values("t")
        )
        solved_subq = (
            CTFSubmission.objects.filter(participant_id=OuterRef("pk"), is_correct=True)
            .order_by()
            .values("participant_id")
            .annotate(c=Count("id"))
            .values("c")
        )
        award_subq = (
            CTFAward.objects.filter(participant_id=OuterRef("pk"))
            .order_by()
            .values("participant_id")
            .annotate(t=Coalesce(Sum("points"), 0))
            .values("t")
        )
        return qs.annotate(
            _submission_score=Coalesce(Subquery(submission_subq, output_field=IntegerField()), 0),
            _award_score=Coalesce(Subquery(award_subq, output_field=IntegerField()), 0),
            _total_score=F("_submission_score") + F("_award_score"),
            _solved_count=Coalesce(Subquery(solved_subq, output_field=IntegerField()), 0),
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
        "submitted_at",
        "ip_address",
    ]
    list_filter = ["is_correct", "challenge__event", "submitted_at"]
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
                "fields": ["ip_address", "submitted_at"],
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
