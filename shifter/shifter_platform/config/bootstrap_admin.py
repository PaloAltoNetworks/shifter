"""Shared bootstrap admin role helpers for production auth providers."""

from __future__ import annotations

from typing import Any

from django.conf import settings


def apply_bootstrap_admin_flags(user: Any, email: str) -> None:
    """Apply env-configured staff/superuser flags to the matching user."""
    normalized_email = email.strip().lower()
    superuser_emails = {
        configured_email.strip().lower()
        for configured_email in getattr(settings, "PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS", [])
        if configured_email.strip()
    }
    staff_emails = {
        configured_email.strip().lower()
        for configured_email in getattr(settings, "PLATFORM_BOOTSTRAP_STAFF_EMAILS", [])
        if configured_email.strip()
    }

    is_superuser = normalized_email in superuser_emails
    is_staff = is_superuser or normalized_email in staff_emails

    updates: list[str] = []
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        updates.append("is_staff")
    if user.is_superuser != is_superuser:
        user.is_superuser = is_superuser
        updates.append("is_superuser")

    if updates:
        user.save(update_fields=updates)
