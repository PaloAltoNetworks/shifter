"""Shared bootstrap admin role helpers for production auth providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings

from shared.verified_identity import VerifiedIdentity

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def apply_bootstrap_admin_flags(user: User, identity: VerifiedIdentity) -> list[str]:
    """Apply env-configured staff/superuser flags to ``user`` from verified identity evidence.

    Requires a :class:`~shared.verified_identity.VerifiedIdentity` so a caller
    cannot elevate a user from a bare, unverified email string (issue #1521);
    only ``identity.email`` -- evidence that has already passed strict
    ``email_verified is True`` verification -- is compared against the
    runtime bootstrap email lists. Those lists remain selectors, never an
    identity key.

    Returns:
        The list of field names actually changed (``["is_staff"]``,
        ``["is_superuser"]``, both, or empty when the user's flags already
        matched policy), so callers can decide whether a security-mutation
        audit row is warranted.

    Raises:
        TypeError: If ``identity`` is not a :class:`VerifiedIdentity` instance.
    """
    if not isinstance(identity, VerifiedIdentity):
        raise TypeError("apply_bootstrap_admin_flags requires a VerifiedIdentity instance")

    normalized_email = identity.email.strip().lower()
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

    return updates
