"""Converge existing soft-deleted accounts on is_active=False (PLAT-236, #1943).

Historically ``mark_user_deleted`` set only ``profile.deleted_at`` and left
``User.is_active`` unchanged, so a soft-deleted account could still hold a
session or re-login. ``User.is_active`` is the sole authentication-enforcement
bit, so this one-time data migration disables any user whose profile is already
soft-deleted. It is reversible only in the trivial no-op sense: reactivation is
an explicit administrator action, never an automatic migration rollback.
"""

from __future__ import annotations

from django.db import migrations


def _disable_soft_deleted(apps, schema_editor):
    UserProfile = apps.get_model("management", "UserProfile")
    User = apps.get_model("auth", "User")
    deleted_user_ids = list(UserProfile.objects.filter(deleted_at__isnull=False).values_list("user_id", flat=True))
    if deleted_user_ids:
        User.objects.filter(id__in=deleted_user_ids, is_active=True).update(is_active=False)


def _noop_reverse(apps, schema_editor):
    # Reactivation is an explicit administrator action; never auto-reactivate.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0011_userprofile_suspended_at"),
    ]

    operations = [
        migrations.RunPython(_disable_soft_deleted, _noop_reverse),
    ]
