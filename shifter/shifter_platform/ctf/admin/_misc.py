"""Admin classes for CTF notifications, scheduled tasks, files, and templates."""

from __future__ import annotations

from django.contrib import admin
from django.utils.html import format_html

from ctf.models import (
    CTFChallengeFile,
    CTFChallengePrerequisite,
    CTFEmailTemplate,
    CTFNotification,
    CTFScheduledTask,
)

from ._base import SoftDeleteAdminMixin


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


@admin.register(CTFEmailTemplate)
class CTFEmailTemplateAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    """Admin for per-event email template overrides."""

    list_display = [
        "event",
        "notification_type",
        "subject",
        "is_deleted_display",
    ]
    list_filter = ["notification_type", "event", "deleted_at"]
    search_fields = ["event__name", "subject"]
    ordering = ["event", "notification_type"]
    readonly_fields = ["id", "created_at", "updated_at", "deleted_at"]

    fieldsets = [
        (
            None,
            {
                "fields": ["event", "notification_type", "subject"],
            },
        ),
        (
            "Template Content",
            {
                "fields": ["html_body", "text_body"],
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
    def is_deleted_display(self, obj: CTFEmailTemplate) -> bool:
        """Display soft delete status."""
        return obj.is_deleted
