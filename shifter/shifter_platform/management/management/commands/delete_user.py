"""Delete a Django user by email (testing utility)."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import ProtectedError

from shared.log_sanitize import safe_log_value


class Command(BaseCommand):
    """Hard-delete a portal user by email for test-state reset."""

    help = "Delete a Django user by email (testing utility)"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("email", help="Email address of the user to delete")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the user that would be deleted without removing it",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        email = str(options["email"]).strip()
        if not email:
            raise CommandError("email is required")

        user_model = get_user_model()
        matches = list(user_model.objects.filter(email__iexact=email).order_by("pk"))
        if not matches:
            self.stdout.write(f"No user found for email={safe_log_value(email)}")
            return
        if len(matches) > 1:
            raise CommandError(f"Ambiguous email match: {len(matches)} users share email={safe_log_value(email)}")
        user = matches[0]

        if options["dry_run"]:
            self.stdout.write(f"Would delete user id={user.id} email={safe_log_value(email)}")
            return

        try:
            user.delete()
        except ProtectedError as exc:
            raise CommandError(
                "User delete blocked by protected related records; clean up dependent data first"
            ) from exc

        self.stdout.write(self.style.SUCCESS(f"Deleted user email={safe_log_value(email)}"))
