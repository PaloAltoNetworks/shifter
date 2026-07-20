"""Inline admin classes for CTF models."""

from __future__ import annotations

from django.contrib import admin

from ctf.models import (
    CTFAward,
    CTFChallenge,
    CTFChallengeFile,
    CTFChallengePrerequisite,
    CTFParticipant,
    CTFScheduledTask,
    CTFSubmission,
    CTFTeam,
)


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
