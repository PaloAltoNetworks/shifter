"""Rebuild the materialized CTF leaderboard columns from authoritative rows.

The live scoreboard and participant-rank reads are served from the
``cached_score`` / ``cached_solve_count`` / ``last_solve_at`` columns on
``CTFParticipant`` and ``CTFTeam`` (issue #850). Those columns are maintained
incrementally on submit / award / disqualify / team-change, but they are derived
state: this command rebuilds them from the authoritative ``CTFSubmission`` /
``CTFAward`` rows, so any drift can be repaired and the materialized state is
always recoverable.

Usage:
    python manage.py ctf_recompute_leaderboard
    python manage.py ctf_recompute_leaderboard --event <event-uuid>
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from ctf.services.scoring import recompute_event_leaderboard


class Command(BaseCommand):
    """Recompute materialized leaderboard columns for all events or one event."""

    help = "Rebuild materialized CTF leaderboard columns from authoritative submissions/awards."

    def add_arguments(self, parser: Any) -> None:
        """Register command arguments."""
        parser.add_argument(
            "--event",
            dest="event_id",
            default=None,
            help="Limit the rebuild to a single event UUID (default: all events).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Run the recompute and report how many rows were rebuilt."""
        event_id = options.get("event_id")
        if event_id is not None:
            from uuid import UUID

            try:
                event_id = UUID(str(event_id))
            except (ValueError, TypeError) as exc:
                raise CommandError(f"Invalid --event UUID: {event_id}") from exc

        participants, teams = recompute_event_leaderboard(event_id)
        scope = f"event {event_id}" if event_id is not None else "all events"
        self.stdout.write(
            self.style.SUCCESS(f"Recomputed CTF leaderboard for {scope}: {participants} participants, {teams} teams.")
        )
