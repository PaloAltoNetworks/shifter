"""Prune expired WebSocket notification queue rows."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from shared.notifications import prune_expired_notifications


class Command(BaseCommand):
    """Delete expired shared WebSocket notifications."""

    help = "Delete expired shared WebSocket notification queue rows."

    def handle(self, *args, **options) -> None:
        """Run notification queue pruning."""
        deleted = prune_expired_notifications()
        suffix = "" if deleted == 1 else "s"
        self.stdout.write(f"Deleted {deleted} expired WebSocket notification{suffix}.")
