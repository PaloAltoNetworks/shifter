"""Purge scoped CTF communications past their retention window (ADR-051, #2048)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from ctf.services.communication import purge_expired_communications


class Command(BaseCommand):
    """Hard-purge communication campaigns whose retention window has elapsed."""

    help = "Purge scoped CTF communications retained past CTF_COMMUNICATION_RETENTION_DAYS."

    def handle(self, *args, **options) -> None:
        """Run the communication retention purge and report bounded counts."""
        result = purge_expired_communications()
        self.stdout.write(
            "Purged {campaigns_purged} campaign(s), {revisions_purged} revision(s), "
            "{snapshots_purged} recipient snapshot(s).".format(**result)
        )
