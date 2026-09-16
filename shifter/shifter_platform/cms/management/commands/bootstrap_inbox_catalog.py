"""Register the in-box scenario bootstrap seed through the uniform ingestion path (#1578).

Loads the declared in-box pack manifest and registers each entry through the same
:func:`cms.services.register_pack` service an operator uses — the in-box seed
has no privileged load path (ADR-053/ADR-034). Exact already-registered
identities are no-ops; drift is a visible failure, so deploy retries are safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError, CommandParser

from cms.exceptions import CMSError
from cms.scenarios.inbox import register_inbox_packs

if TYPE_CHECKING:
    from django.contrib.auth.models import User

user_model = get_user_model()


class Command(BaseCommand):
    """Bootstrap the in-box seed through the uniform ingestion service."""

    help = "Register the in-box scenario bootstrap seed through the uniform ingestion service (#1578)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the registering-actor argument."""
        parser.add_argument("--actor", required=True, help="Username of the registering (system/admin) user.")

    def handle(self, *args: Any, **options: Any) -> None:
        """Register the declared in-box packs, surfacing failures cleanly."""
        actor = self._resolve_actor(options["actor"])
        try:
            registered = register_inbox_packs(actor=actor)
        except (CMSError, PermissionDenied, TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Registered {len(registered)} in-box pack(s)."))

    def _resolve_actor(self, username: str) -> User:
        """Return the registering user or raise a clean ``CommandError``."""
        try:
            return user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"actor '{username}' not found") from exc
