"""Plaintext static flags with an optional ``FLAG{...}`` / ``{...}`` wrapper (CTF-104).

Static flags are stored as their normalized inner value and a submission is
accepted as ``FLAG{v}`` (any case of "flag"), ``{v}``, or bare ``v``.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from ctf.models import CTFFlag
from ctf.models.flag import normalize_static_flag


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("FLAG{abc}", "abc"),
        ("flag{abc}", "abc"),
        ("{abc}", "abc"),
        ("abc", "abc"),
        ("  FLAG{abc}  ", "abc"),
        ("FLAG{a{b}c}", "a{b}c"),
        ("FLAG{abc", "FLAG{abc"),
        ("NOTFLAG{abc}", "NOTFLAG{abc}"),
    ],
)
def test_normalize_static_flag(raw, normalized):
    assert normalize_static_flag(raw) == normalized


@pytest.mark.django_db
def test_model_keeps_static_values_canonical_on_every_write_path(ctf_challenge):
    direct = CTFFlag.objects.create(challenge=ctf_challenge, flag_type="static", value="FLAG{direct}", order=5)
    regex = CTFFlag.objects.create(challenge=ctf_challenge, flag_type="regex", value=r"^\{x\}$", order=6)

    assert direct.value == "direct"
    # Only static values are normalized; a regex pattern is stored as written.
    assert regex.value == r"^\{x\}$"
    with pytest.raises(ValidationError):
        CTFFlag.objects.create(challenge=ctf_challenge, flag_type="static", value="FLAG{}", order=7)


@pytest.mark.django_db
def test_added_flag_accepts_every_wrapper_form_end_to_end(ctf_event, organizer_user):
    from ctf.models import CTFChallenge
    from ctf.services.challenge import add_flag, verify_flag

    challenge = CTFChallenge.objects.create(
        event=ctf_event, name="Wrapped", description="x", category="web", points=100
    )
    flag = add_flag(challenge.pk, {"flag_type": "static", "flag": "FLAG{0123456789abcdef}"}, actor_id=organizer_user.pk)

    assert flag.value == "0123456789abcdef"
    for submission in ("FLAG{0123456789abcdef}", "flag{0123456789abcdef}", "{0123456789abcdef}", "0123456789abcdef"):
        assert verify_flag(challenge, submission), submission
    assert not verify_flag(challenge, "FLAG{fedcba9876543210}")


BEFORE = [("ctf", "0063_ctfparticipant_principal_uuid")]
AFTER = [("ctf", "0064_ctfflag_plaintext_value")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor.loader.build_graph()
    return executor.loader.project_state(targets).apps


@pytest.fixture
def at_before():
    """Yield the historical registry at 0063 (``flag_hash`` still present)."""
    apps = _migrate(BEFORE)
    try:
        yield apps
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM ctf_flag")
            cursor.execute("DELETE FROM ctf_challenge")
            cursor.execute("DELETE FROM ctf_event")
            cursor.execute("DELETE FROM auth_user WHERE username = 'mig-plaintext-owner'")
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_migration_removes_only_unrecoverable_static_hashes(at_before):
    user = at_before.get_model("auth", "User").objects.create(username="mig-plaintext-owner")
    now = timezone.now()
    event = at_before.get_model("ctf", "CTFEvent").objects.create(
        name="Mig Plaintext Event",
        description="migration fixture",
        created_by=user,
        status="draft",
        event_start=now,
        event_end=now,
        scenario_id="basic",
    )
    challenge = at_before.get_model("ctf", "CTFChallenge").objects.create(
        event=event, name="Mig Plaintext Challenge", description="x", category="web", points=100
    )
    flag_model = at_before.get_model("ctf", "CTFFlag")
    rows = {
        "bcrypt": ("static", "$2b$12$legacyhashvalue"),
        "pbkdf2": ("static", "pbkdf2:salt:digest"),
        "sha256": ("static", "sha256:salt:digest"),
        "plain": ("static", "already-plain"),
        "regex": ("regex", r"^flag\{.*\}$"),
        "programmable": ("programmable", "programmable"),
    }
    for order, (flag_type, stored) in enumerate(rows.values()):
        flag_model.objects.create(challenge=challenge, flag_type=flag_type, flag_hash=stored, order=order)

    after = _migrate(AFTER)

    remaining = set(after.get_model("ctf", "CTFFlag").objects.values_list("flag_type", "value"))
    assert remaining == {rows["plain"], rows["regex"], rows["programmable"]}
