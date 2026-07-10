"""Behavior tests for the delete_user management command."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import ProtectedError

User = get_user_model()


@pytest.mark.django_db
def test_delete_user_removes_matching_user() -> None:
    user = User.objects.create_user(username="delme", email="delme@test.example", password="x")
    user_id = user.id

    call_command("delete_user", "delme@test.example")

    assert not User.objects.filter(pk=user_id).exists()


@pytest.mark.django_db
def test_delete_user_is_case_insensitive() -> None:
    user = User.objects.create_user(username="delme2", email="DelMe2@Test.Example", password="x")
    user_id = user.id

    call_command("delete_user", "delme2@test.example")

    assert not User.objects.filter(pk=user_id).exists()


@pytest.mark.django_db
def test_delete_user_no_match_is_idempotent(capsys) -> None:
    call_command("delete_user", "missing@test.example")
    assert "No user found" in capsys.readouterr().out


@pytest.mark.django_db
def test_delete_user_dry_run_leaves_user() -> None:
    user = User.objects.create_user(username="dry", email="dry@test.example", password="x")

    call_command("delete_user", "dry@test.example", dry_run=True)

    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_delete_user_rejects_ambiguous_email() -> None:
    User.objects.create_user(username="dup1", email="Dup@test.example", password="x")
    User.objects.create_user(username="dup2", email="dup@test.example", password="x")

    with pytest.raises(CommandError, match="Ambiguous email match"):
        call_command("delete_user", "dup@test.example")


@pytest.mark.django_db
def test_delete_user_rejects_blank_email() -> None:
    with pytest.raises(CommandError, match="email is required"):
        call_command("delete_user", "   ")


@pytest.mark.django_db
def test_delete_user_propagates_protected_error(monkeypatch) -> None:
    user = User.objects.create_user(username="prot", email="prot@test.example", password="x")

    def _raise_protected(self, *_args, **_kwargs):
        raise ProtectedError("blocked", set())

    monkeypatch.setattr(User, "delete", _raise_protected)

    with pytest.raises(CommandError, match="protected related records"):
        call_command("delete_user", user.email)
