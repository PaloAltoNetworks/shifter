"""Backfill the materialized CTF leaderboard columns (issue #850).

Populates ``cached_score`` / ``cached_solve_count`` / ``last_solve_at`` on
existing CTFParticipant and CTFTeam rows (and ``cached_member_count`` on teams)
from the authoritative CTFSubmission / CTFAward rows, using the same aggregation
the live read paths use. The runtime equivalent lives in
``ctf.services.scoring._maintenance``; this migration is self-contained against
historical models so it does not depend on service code.
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import Count, Max, Sum
from django.db.models.functions import Coalesce

# Eligible (registered, non-disqualified) participant statuses, mirroring
# ctf.services.participant.eligible_participant_q at the time of this migration.
_PLAYING_STATUSES = ("registered", "active", "completed")


def _backfill(apps, schema_editor):
    """Compute materialized leaderboard columns from authoritative rows."""
    CTFParticipant = apps.get_model("ctf", "CTFParticipant")
    CTFTeam = apps.get_model("ctf", "CTFTeam")
    CTFSubmission = apps.get_model("ctf", "CTFSubmission")
    CTFAward = apps.get_model("ctf", "CTFAward")

    for participant_id in CTFParticipant.objects.values_list("id", flat=True).iterator():
        submissions = CTFSubmission.objects.filter(
            participant_id=participant_id,
            is_correct=True,
        ).aggregate(
            points=Coalesce(Sum("points_awarded"), 0),
            solves=Count("id"),
            last_solve=Max("submitted_at"),
        )
        award_points = CTFAward.objects.filter(participant_id=participant_id).aggregate(
            points=Coalesce(Sum("points"), 0),
        )["points"]
        CTFParticipant.objects.filter(pk=participant_id).update(
            cached_score=submissions["points"] + award_points,
            cached_solve_count=submissions["solves"],
            last_solve_at=submissions["last_solve"],
        )

    for team_id in CTFTeam.objects.values_list("id", flat=True).iterator():
        member_ids = list(
            CTFParticipant.objects.filter(
                team_id=team_id,
                registered_at__isnull=False,
                status__in=_PLAYING_STATUSES,
            ).values_list("id", flat=True)
        )
        if member_ids:
            submissions = CTFSubmission.objects.filter(
                participant_id__in=member_ids,
                is_correct=True,
            ).aggregate(
                points=Coalesce(Sum("points_awarded"), 0),
                solves=Count("challenge_id", distinct=True),
                last_solve=Max("submitted_at"),
            )
            award_points = CTFAward.objects.filter(participant_id__in=member_ids).aggregate(
                points=Coalesce(Sum("points"), 0),
            )["points"]
            score = submissions["points"] + award_points
            solve_count = submissions["solves"]
            last_solve = submissions["last_solve"]
        else:
            score = 0
            solve_count = 0
            last_solve = None
        CTFTeam.objects.filter(pk=team_id).update(
            cached_score=score,
            cached_solve_count=solve_count,
            last_solve_at=last_solve,
            cached_member_count=len(member_ids),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0025_materialize_ctf_leaderboard"),
    ]

    operations = [
        # Reverse is a no-op: the columns are dropped when 0025 is unapplied.
        migrations.RunPython(_backfill, migrations.RunPython.noop),
    ]
