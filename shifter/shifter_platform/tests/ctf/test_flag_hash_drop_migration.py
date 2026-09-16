"""Backfill + drop proof for the CTFChallenge.flag_hash removal (#532).

Migration 0047 backfills a static CTFFlag for any challenge that still relies on
the legacy challenge-level hash, then removes the column. These tests drive the
historical schema with MigrationExecutor to prove the backfill, existing-flag
precedence, soft-deleted recovery, and the fail-loud guard on invalid data.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [("ctf", "0046_content_hydration_receipt")]
AFTER = [("ctf", "0047_drop_challenge_flag_hash")]

pytestmark = [pytest.mark.django_db(transaction=True)]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


@pytest.fixture
def at_before():
    """Yield the historical app registry at state 0046 (flag_hash present)."""
    apps = _migrate(BEFORE)
    try:
        yield apps
    finally:
        # Clear seeded rows with schema-agnostic raw SQL (the column may or may
        # not exist depending on how far the test migrated) before returning to
        # HEAD, so an intentionally-invalid fixture can't block the to-leaf
        # migration (which re-runs 0047's guard).
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ctf_flag")
            cursor.execute("DELETE FROM ctf_challenge")
            cursor.execute("DELETE FROM ctf_event")
            cursor.execute("DELETE FROM auth_user WHERE username LIKE 'mig-owner-%'")
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


_counter = {"n": 0}


def _make_event(apps):
    _counter["n"] += 1
    user = apps.get_model("auth", "User").objects.create(username=f"mig-owner-{_counter['n']}")
    now = timezone.now()
    return apps.get_model("ctf", "CTFEvent").objects.create(
        name=f"Mig Event {_counter['n']}",
        description="migration fixture event",
        created_by=user,
        status="draft",
        event_start=now,
        event_end=now,
        scenario_id="basic",
    )


def _make_challenge(apps, event, *, flag_hash, deleted=False):
    return apps.get_model("ctf", "CTFChallenge").objects.create(
        event=event,
        name=f"Mig Challenge {_counter['n']}-{flag_hash[:6]}",
        description="migration fixture challenge",
        category="web",
        points=100,
        flag_hash=flag_hash,
        deleted_at=timezone.now() if deleted else None,
    )


def test_backfill_creates_static_flag_from_legacy_hash(at_before):
    event = _make_event(at_before)
    challenge = _make_challenge(at_before, event, flag_hash="$2b$12$legacyhashvalue")

    after = _migrate(AFTER)
    Flag = after.get_model("ctf", "CTFFlag")
    flags = list(Flag.objects.filter(challenge_id=challenge.pk))
    assert len(flags) == 1
    assert flags[0].flag_type == "static"
    assert flags[0].flag_hash == "$2b$12$legacyhashvalue"
    assert flags[0].case_sensitive is True
    # Column is gone from the historical model.
    assert "flag_hash" not in {f.name for f in after.get_model("ctf", "CTFChallenge")._meta.get_fields()}


def test_existing_active_flag_is_not_duplicated(at_before):
    event = _make_event(at_before)
    challenge = _make_challenge(at_before, event, flag_hash="$2b$12$legacyhashvalue")
    at_before.get_model("ctf", "CTFFlag").objects.create(
        challenge=challenge,
        flag_hash="$2b$12$canonicalrow",
        flag_type="static",
        case_sensitive=True,
        order=0,
    )

    after = _migrate(AFTER)
    flags = list(after.get_model("ctf", "CTFFlag").objects.filter(challenge_id=challenge.pk))
    assert len(flags) == 1  # canonical row wins; no legacy backfill duplicate
    assert flags[0].flag_hash == "$2b$12$canonicalrow"


def test_soft_deleted_challenge_is_backfilled(at_before):
    event = _make_event(at_before)
    challenge = _make_challenge(at_before, event, flag_hash="$2b$12$deletedhash", deleted=True)

    after = _migrate(AFTER)
    # Recoverable soft-deleted challenges are backfilled so restoring one cannot
    # revive an unverifiable gap.
    assert after.get_model("ctf", "CTFFlag").objects.filter(challenge_id=challenge.pk).count() == 1


def test_active_challenge_without_usable_hash_fails_loudly(at_before):
    event = _make_event(at_before)
    _make_challenge(at_before, event, flag_hash="multi-flag")

    with pytest.raises(Exception, match="no usable legacy hash"):
        _migrate(AFTER)
