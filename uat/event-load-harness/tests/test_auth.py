"""Actor sources must keep credentials out of logs/repr and off world-readable disk."""

import os
import stat

import pytest

from event_load_harness.auth import (
    Actor,
    AuthError,
    ctfd_csv_actors,
    dev_login_actors,
    load_actor_manifest,
)


def test_actor_repr_does_not_leak_secret():
    a = Actor(
        label="actor-0001",
        email="p1@example.com",
        user_type="standard",
        password="hunter2",
        session_cookie="sessionid=abc",
    )
    rendered = f"{a!r} {a!s}".lower()
    assert "hunter2" not in rendered
    assert "sessionid=abc" not in rendered
    assert "p1@example.com" not in rendered  # email withheld too; label is the log id
    assert "actor-0001" in rendered


def test_manifest_rejects_world_or_group_readable_file(tmp_path):
    p = tmp_path / "actors.toml"
    p.write_text('[[actor]]\nemail = "p1@example.com"\npassword = "x"\n')
    p.chmod(0o644)
    with pytest.raises(AuthError, match=r"0600|permission"):
        load_actor_manifest(str(p))


def test_manifest_accepts_0600_and_parses_actors(tmp_path):
    p = tmp_path / "actors.toml"
    p.write_text(
        '[[actor]]\nemail = "p1@example.com"\npassword = "x"\nuser_type = "ctf_participant"\n'
        '[[actor]]\nemail = "p2@example.com"\nsession_cookie = "sessionid=zzz"\n'
    )
    p.chmod(0o600)
    actors = load_actor_manifest(str(p))
    assert len(actors) == 2
    assert actors[0].label == "actor-0001"
    assert actors[0].user_type == "ctf_participant"
    assert actors[1].label == "actor-0002"
    # secret material is loaded but never the repr
    assert actors[0].password == "x"


def test_manifest_missing_file_raises(tmp_path):
    with pytest.raises(AuthError):
        load_actor_manifest(str(tmp_path / "nope.toml"))


def test_manifest_actor_without_any_secret_is_rejected(tmp_path):
    p = tmp_path / "actors.toml"
    p.write_text('[[actor]]\nemail = "p1@example.com"\n')
    p.chmod(0o600)
    with pytest.raises(AuthError, match=r"password|session"):
        load_actor_manifest(str(p))


def test_dev_login_actors_generate_distinct_labels_and_emails():
    actors = dev_login_actors(3, email_pattern="loadtest+{i}@example.com", user_type="ctf_participant")
    assert [a.label for a in actors] == ["actor-0001", "actor-0002", "actor-0003"]
    assert len({a.email for a in actors}) == 3
    assert all(a.user_type == "ctf_participant" for a in actors)


def test_ctfd_csv_actors_is_deferred(tmp_path):
    with pytest.raises(NotImplementedError):
        ctfd_csv_actors(str(tmp_path / "users.csv"))


def test_world_readable_check_respects_actual_mode(tmp_path):
    p = tmp_path / "actors.toml"
    p.write_text('[[actor]]\nemail = "p1@example.com"\npassword = "x"\n')
    p.chmod(0o600)
    # sanity: the file really is 0600 so the accept path is exercised honestly
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert load_actor_manifest(str(p))
