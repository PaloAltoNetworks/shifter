"""Seed deterministic synthetic actors for authenticated Playwright E2E.

DEV/TEST ONLY. This command refuses to run in a production posture, mirroring
the ``config.dev_auth`` gate: it is allowed only when ``DEBUG`` is true or
``ENVIRONMENT`` is ``development``/``test``. It never runs in production.

It seeds only what ``dev_login`` cannot establish for a synthetic actor:
``is_staff`` elevation, the local ``Threat Research`` group, and an
organization the staff actor administers. The organization + admin
``OrganizationMembership`` are created through the real personal-workspace
service. CTF organizer/participant sessions are established through
``dev_login`` at test time and need no seeding here.

Home: this command lives in the ``workspaces`` layer because that is the layer
permitted to compose ``workspaces.services`` and ``shared.auth`` (ADR-001
layering); ``config`` may import neither. Idempotent: safe to re-run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from shared.auth import THREAT_RESEARCH_GROUP
from workspaces.services import resolve_personal_workspace

if TYPE_CHECKING:
    from django.contrib.auth.models import User as DjangoUser

User = get_user_model()

#: Stable synthetic-actor identities the Playwright suite logs in as.
STAFF_EMAIL = "e2e-staff@example.com"
THREAT_EMAIL = "e2e-threat@example.com"
STANDARD_EMAIL = "e2e-standard@example.com"

#: Non-production environments in which seeding is permitted.
_ALLOWED_ENVIRONMENTS = frozenset({"development", "test"})


def _seed_allowed() -> bool:
    """Return True only in a development/test posture (never production)."""
    return bool(settings.DEBUG) or getattr(settings, "ENVIRONMENT", "production") in _ALLOWED_ENVIRONMENTS


class Command(BaseCommand):
    """Seed synthetic E2E actors and preconditions (dev/test only)."""

    help = "Seed deterministic synthetic actors for authenticated Playwright E2E (dev/test only)."

    def handle(self, *args: object, **options: object) -> None:
        """Create the synthetic actors idempotently, refusing in production."""
        if not _seed_allowed():
            raise CommandError("seed_e2e is disabled outside development/test (refusing production posture).")

        staff = self._ensure_user(STAFF_EMAIL, is_staff=True)
        # A personal organization the staff actor administers is created via the
        # real personal-workspace service, which persists the admin
        # OrganizationMembership the workspace-console lifecycle journey needs.
        resolve_personal_workspace(staff)

        self._ensure_user(STANDARD_EMAIL)

        threat = self._ensure_user(THREAT_EMAIL)
        group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
        threat.groups.add(group)

        self.stdout.write(
            self.style.SUCCESS(
                "Seeded E2E actors: "
                f"{STAFF_EMAIL} (staff + org-admin), "
                f"{THREAT_EMAIL} (threat-research), "
                f"{STANDARD_EMAIL} (standard)."
            )
        )

    @staticmethod
    def _ensure_user(email: str, *, is_staff: bool = False) -> DjangoUser:
        """Get-or-create a synthetic user, elevating (never downgrading) flags."""
        user, created = User.objects.get_or_create(
            username=email,
            defaults={"email": email, "is_active": True, "is_staff": is_staff},
        )
        if created:
            return user
        fields: list[str] = []
        if not user.is_active:
            user.is_active = True
            fields.append("is_active")
        if is_staff and not user.is_staff:
            user.is_staff = True
            fields.append("is_staff")
        if fields:
            user.save(update_fields=fields)
        return user
