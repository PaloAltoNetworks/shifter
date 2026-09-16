"""Operator ``register_pack`` management command (#1578, ADR-034).

The CLI is a thin operator entrypoint onto ``cms.services.register_pack``; the
service owns validation and authorization. These tests cover the wiring and the
error surface.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import PackDigestError, pack_digest

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_actor(django_user_model):
    return django_user_model.objects.create_user(
        username="cli-actor@example.com",
        email="cli-actor@example.com",
        is_staff=True,
    )


# A repo pack's catalog id is bound to its validated identity.
CLI_FIXTURE_NAME = "cli-fixture"


@pytest.fixture
def repo_pack(make_pack, tmp_path, monkeypatch):
    from django.conf import settings

    make_pack(tmp_path / "packs" / CLI_FIXTURE_NAME, name=CLI_FIXTURE_NAME)
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    return f"packs/{CLI_FIXTURE_NAME}"


def _args(package_ref: str, actor: str, **overrides) -> list[str]:
    values = {
        "--scenario-id": CLI_FIXTURE_NAME,
        "--source-kind": "repo",
        "--contract-profile": "shifter",
        "--package-ref": package_ref,
        "--package-version": "0.1.0",
        "--package-digest": "sha256:" + "a" * 64,
        "--actor": actor,
    }
    values.update(overrides)
    if "--package-digest" not in overrides and values["--source-kind"] == "repo":
        from django.conf import settings

        with suppress(PackDigestError, OSError):
            values["--package-digest"] = pack_digest(Path(settings.RAES_PACKAGE_ROOT) / package_ref)
    args: list[str] = []
    for flag, value in values.items():
        args.extend([flag, value])
    return args


def test_command_registers_pack(admin_actor, repo_pack):
    call_command("register_pack", *_args(repo_pack, admin_actor.username))
    assert RaesPackageSource.objects.filter(scenario_id=CLI_FIXTURE_NAME).exists()


def test_command_errors_on_unknown_actor(repo_pack):
    args = _args(repo_pack, "nobody@example.com")
    with pytest.raises(CommandError):
        call_command("register_pack", *args)


def test_command_errors_on_domain_failure(admin_actor, repo_pack):
    # A caller-supplied identity that differs from the validated pack identity
    # is surfaced as a bounded CommandError, not a traceback.
    args = _args(repo_pack, admin_actor.username, **{"--scenario-id": "basic"})
    with pytest.raises(CommandError, match="validated identity"):
        call_command("register_pack", *args)
